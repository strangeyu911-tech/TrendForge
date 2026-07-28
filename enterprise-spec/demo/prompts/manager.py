"""Prompt 版本管理器"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from config import PROMPTS_DIR


# 内置 Prompt 模板（也可从 prompts/*.json 加载）
BUILTIN_TEMPLATES: dict[str, dict[str, dict]] = {
    "writer": {
        "deep_dive": {
            "v1.0.0": {
                "template": (
                    "# Role\n你是资深{{ category }}新闻编辑。\n\n"
                    "# Task\n基于以下证据撰写一篇{{ template_type }}稿件。\n\n"
                    "# Evidence\n{% for ev in evidences %}\n[{{ ev.evidence_id }}] ({{ ev.source_name }})\n{{ ev.content }}\n{% endfor %}\n\n"
                    "# Topic\n{{ topic.title }}\n\n# Output JSON"
                ),
                "changelog": "初始版本",
            },
            "v2.0.0": {
                "template": (
                    "# Role\n你是资深{{ category }}新闻编辑。\n\n"
                    "# Task\n基于以下证据撰写一篇{{ template_type }}稿件。\n\n"
                    "# Constraints\n- 字数 {{ constraints.min_words }}~{{ constraints.max_words }}\n"
                    "- 开头 50 字内必须出现核心事实\n"
                    "- 必须引用证据 ID [ev_xxx]\n- 禁止编造\n\n"
                    "# Evidence\n{% for ev in evidences %}\n[{{ ev.evidence_id }}] ({{ ev.source_name }}, {{ ev.published_at }})\n{{ ev.content }}\n{% endfor %}\n\n"
                    "# Topic\n{{ topic.title }}\n角度：{{ topic.suggested_angles }}\n\n# Output JSON"
                ),
                "changelog": "增加开头强事实约束 + 引用强制",
            },
            "v2.0.1": {
                "template": (
                    "# Role\n你是资深{{ category }}新闻编辑。\n\n"
                    "# Task\n基于以下证据撰写一篇{{ template_type }}稿件。\n\n"
                    "# Constraints\n- 字数 {{ constraints.min_words }}~{{ constraints.max_words }}\n"
                    "- 开头 50 字内必须出现核心事实\n"
                    "- 所有数字必须带 [ev_xxx] 引用\n"
                    "- 必须引用证据 ID [ev_xxx]\n- 禁止编造\n- 禁止夸张词\n\n"
                    "# Evidence\n{% for ev in evidences %}\n[{{ ev.evidence_id }}] ({{ ev.source_name }}, {{ ev.published_at }}, 可信度{{ ev.credibility }})\n{{ ev.content }}\n{% endfor %}\n\n"
                    "# Topic\n{{ topic.title }}\n角度：{{ topic.suggested_angles }}\n\n"
                    "# Output Schema\n{title,summary,body:[{type,text,citations}],tags,cover_suggestion}\n\n# Output"
                ),
                "changelog": "修正引用格式示例 + 数字引用强制（修复 Bad Case H02）",
            },
        },
    },
    "planner": {
        "default": {
            "v1.2.0": {"template": "选题策划 Prompt v1.2.0", "changelog": "增加去重策略"},
        }
    },
    "reviewer": {
        "default": {
            "v1.3.0": {"template": "审核 Prompt v1.3.0", "changelog": "增加合规规则"},
        }
    },
}


class PromptManager:
    """Prompt 版本管理：加载、渲染、版本切换、A/B 分桶"""

    def __init__(self):
        self.templates = BUILTIN_TEMPLATES
        self.experiments: dict[str, dict] = {}
        self.assignments: dict[str, str] = {}  # content_id -> variant

    def get_versions(self, agent: str, scene: str) -> list[str]:
        return list(self.templates.get(agent, {}).get(scene, {}).keys())

    def get_latest(self, agent: str, scene: str) -> str:
        versions = self.get_versions(agent, scene)
        return versions[-1] if versions else "v1.0.0"

    def render(self, agent: str, scene: str, language: str, version: str, variables: dict) -> str:
        tpl_data = self.templates.get(agent, {}).get(scene, {}).get(version)
        if not tpl_data:
            # 回退到最新版
            latest = self.get_latest(agent, scene)
            tpl_data = self.templates.get(agent, {}).get(scene, {}).get(latest, {})
            version = latest
        template = tpl_data.get("template", "")
        # 简单变量替换（不依赖 Jinja2，保证无第三方依赖）
        rendered = self._simple_render(template, variables)
        return rendered

    def _simple_render(self, template: str, variables: dict) -> str:
        """简易模板渲染：支持 {{ a.b }} 和 {% for %}"""
        import re
        # 处理 for 循环
        def render_for(match):
            item_name = match.group(1)
            list_expr = match.group(2)
            body = match.group(3)
            items = self._eval(list_expr, variables) or []
            out = []
            for item in items:
                local_vars = {**variables, item_name: item}
                out.append(self._simple_render(body, local_vars))
            return "".join(out)
        template = re.sub(
            r"{%\s*for\s+(\w+)\s+in\s+([^%]+)\s*%}(.*?){%\s*endfor\s*%}",
            render_for, template, flags=re.DOTALL,
        )
        # 处理变量
        def render_var(match):
            expr = match.group(1).strip()
            val = self._eval(expr, variables)
            return str(val) if val is not None else ""
        template = re.sub(r"{{\s*([^}]+)\s*}}", render_var, template)
        return template

    def _eval(self, expr: str, variables: dict) -> Any:
        parts = expr.strip().split(".")
        val = variables
        for p in parts:
            if val is None:
                return None
            if isinstance(val, dict):
                val = val.get(p)
            elif isinstance(val, list):
                try:
                    val = val[int(p)]
                except (ValueError, IndexError):
                    return None
            else:
                val = getattr(val, p, None)
        return val

    # ====== A/B 实验 ======
    def create_experiment(self, exp_id: str, agent: str, scene: str,
                          control: str, treatment: str, split: dict | None = None) -> dict:
        split = split or {"control": 0.5, "treatment": 0.5}
        self.experiments[exp_id] = {
            "experiment_id": exp_id, "agent": agent, "scene": scene,
            "control": control, "treatment": treatment, "split": split,
            "assignments": {"control": [], "treatment": []},
            "status": "running", "created_at": datetime.now().isoformat(),
        }
        return self.experiments[exp_id]

    def assign(self, exp_id: str, content_id: str) -> str:
        """按分桶比例分配 variant"""
        exp = self.experiments[exp_id]
        # 已分配则直接返回
        for variant, ids in exp["assignments"].items():
            if content_id in ids:
                return variant
        # 哈希分桶
        import hashlib
        h = int(hashlib.md5(f"{exp_id}:{content_id}".encode()).hexdigest()[:8], 16) % 100
        cumulative = 0
        assigned = "control"
        for variant, ratio in exp["split"].items():
            cumulative += int(ratio * 100)
            if h < cumulative:
                assigned = variant
                break
        exp["assignments"][assigned].append(content_id)
        self.assignments[content_id] = assigned
        return assigned

    def get_variant_version(self, exp_id: str, variant: str) -> str:
        exp = self.experiments[exp_id]
        return exp[variant]

    def conclude(self, exp_id: str, winner: str, metrics: dict) -> dict:
        exp = self.experiments[exp_id]
        exp["status"] = "concluded"
        exp["winner"] = winner
        exp["result"] = metrics
        return exp

    def list_experiments(self) -> list[dict]:
        return list(self.experiments.values())
