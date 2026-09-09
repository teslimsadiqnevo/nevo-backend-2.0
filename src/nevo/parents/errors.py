class ParentInsightError(Exception):
    code = "parent_insight_error"
    public_message = "That information is not available."


class ChildNotLinkedError(ParentInsightError):
    code = "child_not_linked"
    public_message = "You are not listed as a parent or guardian for this learner."
