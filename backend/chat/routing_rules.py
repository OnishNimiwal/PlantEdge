"""
Routing rule definitions (data only). The decision logic lives in router.py.

All patterns are case-insensitive regular expressions matched on the user
message. To tune routing, edit these lists; no other code needs to change.

Intents
-------
coding       - strong signals route to the coder model on their own; weak signals
               only count together with another coding signal or a code action verb.
vision       - a *visual target* ("this drawing", "the attached photo", "in the image")
               or a visual action; plain topic mentions ("what is a P&ID?") do not count.
properties   - visual properties (colour, shape, position...). Only mean "vision" when
               an image is attached or available from the conversation/document.
followup     - words that refer back to a previous turn ("it", "which component").
text_extraction - "read / transcribe / extract the text" (used for OCR routing).
document_text_task - summarise / list findings etc.: with an attached image this is
               answered from OCR text (qwen3); together with a visual question the
               vision model gets both the image and the OCR text.
negative     - phrases that neutralise a keyword used in a non-technical sense.
"""

# --- coding ---------------------------------------------------------------

CODING_STRONG = [
    r"```",                                            # code block
    # Bug descriptions without the word "code" (L7: "my loop never ends")
    r"\b(?:infinite|endless)\s+loop\b",
    r"\bloop\s+(?:never|doesn't|does\s+not|won't|will\s+not)\s+(?:end|ends|stop|stops|terminate|finish)\b",
    r"\b(?:it|my\s+\w+)\s+(?:throws|segfaults|won't\s+compile|doesn't\s+compile)\b",
    r"\breturns?\s+(?:none|null|undefined|nan)\b",
    r"\b(?:null|nil)\s+pointer\b|\bundefined\s+is\s+not\b|\bindentation\s+error\b",
    r"\b(?:pip|npm|yarn)\s+(?:install|run)\b|\bregex\b|\bregular\s+expression\b",
    r"traceback \(most recent call last\)",
    r"\b[A-Z][a-z]+(?:Error|Exception)\b",             # SyntaxError, NullPointerException
    r"\bstack ?trace\b",
    r"\bsegfault\b|\bsegmentation fault\b",
    r"\b(?:fix|debug|refactor|review|optimi[sz]e|test)\s+(?:my|this|the|a)\s+"
    r"(?:script|code|program|function|method|class|query|bug|regex|app)\b",
    r"\b(?:write|create|generate|implement|build|code)\s+(?:me\s+)?(?:a|an|the|some)?\s*"
    r"(?:\w+\s+){0,3}(?:function|script|program|class|method|query|regex|endpoint|api|"
    r"unit tests?|algorithm|code)\b",
    r"\bmy (?:script|code|program)\b",
    r"\b(?:python|javascript|typescript|java|c\+\+|c#|golang|kotlin|php|bash|powershell|sql)\b",
    r"\b(?:django|flask|fastapi|numpy|pandas|node\.?js|react\s+(?:component|app|hook|js)|reactjs)\b",
    r"\bcompile(?:r)? error\b|\bsyntax error\b|\bruntime error\b",
    r"\bunit tests?\b|\bpull request\b|\bgit (?:commit|merge|rebase)\b",
    r"\b\w+\.(?:py|js|ts|jsx|tsx|java|cpp|c|h|sql|sh)\b",   # file names
    r"^\s*(?:def|class|import|from|#include|public|function)\s+\w+",  # code pasted inline
]

CODING_WEAK = [
    r"\bcode\b", r"\bcoding\b", r"\bfunction\b", r"\bclass\b", r"\bprogram\b",
    r"\bprogramming\b", r"\berror\b", r"\balgorithm\b", r"\bdebug\w*\b", r"\bbug\b",
    r"\bscript\b", r"\breact\b", r"\brust\b", r"\bvariable\b", r"\bloop\b", r"\bcompile\b",
]

# A weak coding keyword counts when combined with one of these action verbs.
CODE_ACTIONS = r"\b(?:write|fix|debug|implement|refactor|optimi[sz]e|compile|run|execute|convert|port)\b"

CODING_NEGATIVE = [
    r"\btraining program(?:me)?s?\b", r"\bmaintenance program(?:me)?s?\b",
    r"\binspection program(?:me)?s?\b", r"\bsafety program(?:me)?s?\b",
    r"\bprogram(?:me)? (?:manager|management|of work)\b", r"\bprogramme\b",
    r"\bhuman error\b", r"\bmargin of error\b", r"\berror (?:rate|margin|band)\b",
    r"\btrial and error\b", r"\bmeasurement error\b", r"\boperator error\b",
    r"\bworld[- ]class\b", r"\bfirst[- ]class\b", r"\bclass (?:of|room)\b", r"\bpressure class\b",
    r"\bcode of (?:conduct|practice)\b", r"\b(?:safety|building|design|fire|dress|zip|postal|"
    r"colou?r|asme|api|piping|electrical) codes?\b",
    r"\bfunction of (?:a|an|the)\b", r"\bfunctions? as\b",
    r"\brust(?:ing|ed|y)?\b(?! code| program)",       # corrosion, not the language
    r"\breact(?:s|ed|ion)? with\b", r"\bchemical react\w*\b",
]

# --- vision ---------------------------------------------------------------

VISUAL_NOUNS = (
    r"(?:image|images|photo|photos|photograph|photographs|picture|pictures|pic|screenshot|"
    r"screenshots|scan|scans|scanned (?:\w+)|drawing|drawings|diagram|diagrams|p&ids?|"
    r"schematic|schematics|sketch|sketches|figure|blueprint|blueprints|handwritten (?:\w+)|"
    r"handwriting|chart)"
)

# A visual noun counts as a *target* only when it is pointed at.
VISION_TARGET = [
    rf"\b(?:this|these|that|those|my|attached|uploaded|above|following|shown|provided|given)\s+"
    rf"(?:\w+\s+){{0,2}}{VISUAL_NOUNS}",
    rf"\b(?:in|on|from|of|at|inside)\s+the\s+(?:\w+\s+){{0,2}}{VISUAL_NOUNS}",
    rf"\bthe\s+(?:\w+\s+){{0,2}}{VISUAL_NOUNS}\s+(?:shows?|shown|depicts?|attached|above|below|provided)\b",
    rf"^\s*(?:analy[sz]e|describe|inspect|review|examine|interpret|read|check|study|compare)\s+"
    rf"(?:the\s+)?(?:\w+\s+){{0,2}}{VISUAL_NOUNS}",
]

# Weaker target ("the drawing", "the P&ID"): only counts when an image/document is
# available, so "Explain the P&ID symbols for valves" without an image stays general.
VISION_TARGET_IF_AVAILABLE = [
    rf"\bthe\s+(?:\w+\s+){{0,2}}{VISUAL_NOUNS}",
]

VISION_ACTIONS = [
    r"\bvisual(?:ly)? inspect\w*\b", r"\blook at\b", r"\bcan you see\b", r"\bwhat do you see\b",
    r"\bvisible in\b", r"\bshown in\b", r"\bdepicted\b", r"\bin the (?:picture|photo|image)\b",
    r"\bimage understanding\b",
]

VISUAL_PROPERTIES = [
    r"\bcolou?rs?\b", r"\bcolou?red\b", r"\bshape[sd]?\b", r"\bpositions?\b", r"\blocated\b",
    r"\bwhere (?:is|are)\b", r"\b(?:left|right|top|bottom|corner|centre|center)\b",
    r"\b(?:above|below|beneath|next to|beside|behind|in front of|between)\b",
    r"\b(?:largest|smallest|biggest|tallest|longest)\b", r"\bhow (?:big|large|small|many)\b",
    r"\bappearance\b", r"\blooks? like\b", r"\borientation\b", r"\blayout\b", r"\bdamaged?\b",
    r"\bcorroded\b", r"\bcondition\b",
]

FOLLOWUP_MARKERS = [
    r"\b(?:it|its|they|them|their|this|that|these|those|which|what about|and the)\b",
    r"\b(?:component|components|part|parts|item|items|object|objects|element|symbol|symbols)\b",
    r"\b(?:largest|smallest|biggest|most|least|first|second|third|last)\b",
]

TEXT_EXTRACTION = [
    r"\b(?:read|transcribe|extract|copy)\s+(?:out\s+)?(?:all\s+)?(?:the\s+)?(?:text|words|writing|content)\b",
    r"\bwhat does (?:it|this|the \w+) say\b", r"\bocr\b", r"\btext (?:in|from|on) (?:the|this)\b",
]

DOCUMENT_TEXT_TASK = [
    r"\bsummari[sz]e\b", r"\bsummary\b", r"\bkey (?:findings|points|details|items)\b",
    r"\blist (?:all\s+)?(?:the\s+)?(?:findings|recommendations|actions|items|values|readings|dates)\b",
    r"\bwhat (?:are|were) the (?:findings|recommendations|readings|values)\b",
    r"\b(?:inspection|test|maintenance) report\b", r"\btranslate\b",
]

# Visual questions for the OCR-vs-vision decision (in addition to VISUAL_PROPERTIES).
VISUAL_QUESTION = [
    r"\bdescribe\b", r"\bwhat (?:is|does it|do you) (?:shown|show|see)\b", r"\blook(?:s)? like\b",
    r"\bdiagram\b", r"\bdrawing\b", r"\bp&id\b", r"\bphoto\b", r"\bpicture\b", r"\bsymbols?\b",
    r"\bvisual\w*\b", r"\bidentify\b", r"\bdamage\w*\b", r"\bcorro\w+ (?:visible|shown)\b",
]

# Pasted code: share of lines that look like code (see router._code_likeness).
CODE_LINE = r"^\s*(?:def |class |import |from \S+ import |return\b|if .*:$|for .*:$|while .*:$|#include|" \
            r"(?:public|private|static)\s|function\s|const |let |var |SELECT\s|INSERT\s|UPDATE\s)" \
            r"|[;{}]\s*$|\w+\s*\(.*\)\s*[:{;]?\s*$|^\s{4,}\S|==|!=|=>|->"
