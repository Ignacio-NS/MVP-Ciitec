from .base import Evaluator, EvaluatorContext
from .budget import BudgetEvaluator
from .citation_support import CitationSupportEvaluator
from .http_contract import HttpContractEvaluator
from .human_review import HumanReviewEvaluator
from .metamorphic import MetamorphicEvaluator
from .rbac_leak import RbacLeakEvaluator
from .required_fact import RequiredFactEvaluator
from .rubric_llm import RubricLlmEvaluator
from .schema import SchemaEvaluator

# human_review va siempre al final: lee context.sibling_scores de los demas
# evaluadores del mismo caso (ver evaluators/human_review.py).
REGISTRY: dict[str, Evaluator] = {
    e.id: e for e in [
        SchemaEvaluator(), CitationSupportEvaluator(), RequiredFactEvaluator(),
        RbacLeakEvaluator(), BudgetEvaluator(), HttpContractEvaluator(),
        MetamorphicEvaluator(), RubricLlmEvaluator(), HumanReviewEvaluator(),
    ]
}

__all__ = ["Evaluator", "EvaluatorContext", "REGISTRY"]
