"""数据分析模块：CTR/阅读率/Prompt效果分析（Demo 版基于内存数据）"""
from __future__ import annotations
import random
from datetime import datetime, timedelta
from collections import defaultdict
from statistics import mean


class MetricsCollector:
    """采集与聚合内容指标"""

    def __init__(self):
        self.events: list[dict] = []
        self.content_meta: dict[str, dict] = {}

    def record_publish(self, content_id: str, prompt_version: str, category: str, published_at: str):
        self.content_meta[content_id] = {
            "prompt_version": prompt_version, "category": category, "published_at": published_at,
        }

    def simulate_events(self, content_ids: list[str], days: int = 7):
        """为 Demo 生成模拟曝光/点击/阅读事件"""
        for cid in content_ids:
            base_impressions = random.randint(500, 5000)
            base_ctr = random.uniform(0.02, 0.06)
            for d in range(days):
                date = (datetime.now() - timedelta(days=d)).date().isoformat()
                impressions = int(base_impressions * random.uniform(0.7, 1.3))
                clicks = int(impressions * base_ctr * random.uniform(0.8, 1.2))
                reads = int(clicks * random.uniform(0.55, 0.75))
                finishes = int(reads * random.uniform(0.35, 0.5))
                likes = int(reads * random.uniform(0.03, 0.08))
                comments = int(reads * random.uniform(0.01, 0.03))
                shares = int(reads * random.uniform(0.02, 0.05))
                self.events.append({
                    "content_id": cid, "dt": date,
                    "impressions": impressions, "clicks": clicks, "reads": reads,
                    "finishes": finishes, "likes": likes, "comments": comments, "shares": shares,
                })

    def ctr_analysis(self, by: str = "category") -> list[dict]:
        """CTR 分析：按品类或 Prompt 版本聚合"""
        agg = defaultdict(lambda: {"impressions": 0, "clicks": 0, "reads": 0, "finishes": 0})
        for e in self.events:
            meta = self.content_meta.get(e["content_id"], {})
            key = meta.get(by, "unknown")
            for k in ["impressions", "clicks", "reads", "finishes"]:
                agg[key][k] += e[k]
        result = []
        for key, v in agg.items():
            ctr = round(v["clicks"] / v["impressions"], 4) if v["impressions"] else 0
            read_rate = round(v["reads"] / v["clicks"], 4) if v["clicks"] else 0
            finish_rate = round(v["finishes"] / v["reads"], 4) if v["reads"] else 0
            result.append({
                by: key, "impressions": v["impressions"], "clicks": v["clicks"],
                "ctr": ctr, "read_rate": read_rate, "finish_rate": finish_rate,
            })
        result.sort(key=lambda x: x["ctr"], reverse=True)
        return result

    def prompt_effect_analysis(self) -> list[dict]:
        """Prompt 版本效果分析"""
        return self.ctr_analysis(by="prompt_version")

    def funnel_analysis(self) -> dict:
        """漏斗分析"""
        total_imp = sum(e["impressions"] for e in self.events)
        total_click = sum(e["clicks"] for e in self.events)
        total_read = sum(e["reads"] for e in self.events)
        total_finish = sum(e["finishes"] for e in self.events)
        return {
            "impressions": total_imp,
            "clicks": total_click,
            "reads": total_read,
            "finishes": total_finish,
            "ctr": round(total_click / total_imp, 4) if total_imp else 0,
            "read_rate": round(total_read / total_click, 4) if total_click else 0,
            "finish_rate": round(total_finish / total_read, 4) if total_read else 0,
        }

    def ab_test_report(self, control: str, treatment: str) -> dict:
        """简化版 A/B 显著性检验（Z-test 近似）"""
        import math
        def stats(version):
            imp = sum(e["impressions"] for e in self.events
                      if self.content_meta.get(e["content_id"], {}).get("prompt_version") == version)
            clk = sum(e["clicks"] for e in self.events
                      if self.content_meta.get(e["content_id"], {}).get("prompt_version") == version)
            ctr = clk / imp if imp else 0
            return imp, clk, ctr

        n1, x1, p1 = stats(control)
        n2, x2, p2 = stats(treatment)
        if n1 == 0 or n2 == 0:
            return {"error": "insufficient_data", "control": control, "treatment": treatment}

        pooled = (x1 + x2) / (n1 + n2)
        se = math.sqrt(pooled * (1 - pooled) * (1/n1 + 1/n2)) or 1e-9
        z = (p2 - p1) / se
        p_value = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
        significant = p_value < 0.05
        lift = round((p2 - p1) / p1 * 100, 2) if p1 else 0
        return {
            "control": {"version": control, "n": n1, "ctr": round(p1, 4)},
            "treatment": {"version": treatment, "n": n2, "ctr": round(p2, 4)},
            "lift_pct": lift,
            "z_score": round(z, 3),
            "p_value": round(p_value, 4),
            "significant": significant,
            "conclusion": "treatment wins" if significant and p2 > p1 else
                           ("control wins" if significant and p1 > p2 else "no significant difference"),
        }

    def daily_trend(self, days: int = 7) -> list[dict]:
        """每日趋势"""
        agg = defaultdict(lambda: {"impressions": 0, "clicks": 0, "reads": 0})
        for e in self.events:
            agg[e["dt"]]["impressions"] += e["impressions"]
            agg[e["dt"]]["clicks"] += e["clicks"]
            agg[e["dt"]]["reads"] += e["reads"]
        result = []
        for dt in sorted(agg.keys()):
            v = agg[dt]
            result.append({
                "dt": dt,
                "impressions": v["impressions"],
                "clicks": v["clicks"],
                "ctr": round(v["clicks"] / v["impressions"], 4) if v["impressions"] else 0,
            })
        return result[-days:]
