import unittest

from helpers import PROJECT_ROOT  # noqa: F401  (adds the project root to sys.path)
from src.checklist import verification_view


def evaluation(decision="APPROVED", exists=True, approved=True, remaining=114500.0, amount=14500.0,
               category="IT-Ausstattung", special=2, prior=None, budget_error=False):
    budget = ({"error": "Category not found"} if budget_error else
              {"remaining_budget": remaining, "sufficient": remaining >= amount,
               "borderline": remaining < amount <= remaining * 1.05, "konto": "542900"})
    return {
        "decision": decision, "supplier_name": "Dell Technologies", "amount": amount, "category": category,
        "konto": "542900", "procurement_type": "Auftragserweiterung" if prior else "LuD", "prior_contracts": prior or [],
        "supplier_check": {"supplier_name": "Dell Technologies", "exists": exists, "is_approved": approved},
        "budget_check": budget,
        "accessibility_check": {"found": True, "department": category, "total_employees": 20,
                                "employees_with_special_needs": special},
    }


def lines(view):
    return [(c["key"], c["status"], c["code"]) for c in view["checks"]]


class TestVerificationView(unittest.TestCase):
    def test_approved_request(self):
        view = verification_view(evaluation())
        self.assertEqual(view["recommendation"], "APPROVED")
        self.assertEqual(view["reason"]["code"], "approved")
        self.assertEqual(lines(view), [
            ("supplier", "pass", "supplier_ok"), ("budget", "pass", "budget_ok"),
            ("form", "pass", "form_lud"), ("accessibility", "info", "access_needs"),
        ])
        budget = view["checks"][1]["params"]
        self.assertEqual((budget["amount"], budget["left"], budget["after"]), (14500.0, 114500.0, 100000.0))
        self.assertEqual(view["checks"][3]["params"]["hint"], "it")
        # Details: extraction, history, supplier, budget, accessibility; no recommendation step
        self.assertEqual([d["code"] for d in view["details"]], [
            "detail_extraction", "detail_history_new", "detail_supplier_ok", "detail_budget", "detail_access_needs"])

    def test_supplier_problems(self):
        view = verification_view(evaluation("REJECTED", approved=False))
        self.assertEqual(view["reason"], {"code": "supplier_not_approved", "params": {"supplier": "Dell Technologies"}})
        self.assertEqual(lines(view)[0], ("supplier", "fail", "supplier_not_approved"))
        unknown = verification_view(evaluation("REJECTED", exists=False, approved=False))
        self.assertEqual(unknown["reason"]["code"], "supplier_unknown")
        self.assertEqual(lines(unknown)[0], ("supplier", "fail", "supplier_unknown"))

    def test_budget_borderline_exceeded_and_unknown(self):
        borderline = verification_view(evaluation("REQUIRES_REVIEW", remaining=72700.0, amount=76000.0,
                                                  category="Fahrzeuge", special=0))
        self.assertEqual(borderline["reason"]["code"], "borderline")
        self.assertAlmostEqual(borderline["reason"]["params"]["short"], 3300.0)
        self.assertEqual(lines(borderline)[1], ("budget", "warn", "budget_borderline"))
        self.assertEqual(lines(borderline)[3], ("accessibility", "pass", "access_none"))
        exceeded = verification_view(evaluation("REJECTED", remaining=50000.0, amount=76000.0))
        self.assertEqual(exceeded["reason"]["code"], "budget_exceeded")
        self.assertEqual(lines(exceeded)[1], ("budget", "fail", "budget_short"))
        unknown = verification_view(evaluation("REJECTED", budget_error=True))
        self.assertEqual(unknown["reason"]["code"], "budget_unknown")
        self.assertEqual(lines(unknown)[1], ("budget", "fail", "budget_unknown"))

    def test_live_budget_and_extension(self):
        prior = [{"timestamp": "2026-06-14T10:00:00"}, {"timestamp": "2026-10-12T09:00:00"}]
        live = {"remaining_budget": 20000.0, "sufficient": True, "borderline": False, "konto": "542900"}
        view = verification_view(evaluation(prior=prior), live)
        self.assertEqual(view["checks"][1]["params"]["left"], 20000.0)  # checklist: current budget
        self.assertEqual(view["details"][3]["params"]["left"], 114500.0)  # details: what the agent saw
        self.assertEqual(lines(view)[2], ("form", "pass", "form_extension"))
        self.assertEqual(view["checks"][2]["params"]["date"], "2026-10-12T09:00:00")
        self.assertEqual(view["details"][1]["code"], "detail_history_extension")

    def test_accessibility_hints_by_category(self):
        self.assertEqual(verification_view(evaluation(category="Büromaterial"))["checks"][3]["params"]["hint"], "furniture")
        self.assertEqual(verification_view(evaluation(category="Fahrzeuge"))["checks"][3]["params"]["hint"], "general")

    def test_missing_structured_checks_raise(self):
        broken = evaluation()
        del broken["supplier_check"]
        with self.assertRaises(KeyError):
            verification_view(broken)


if __name__ == "__main__":
    unittest.main()
