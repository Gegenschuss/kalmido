"""2.48.0 (#1111): a small, locally learning classifier for documents ("learns from your documents").

Multinomial naive Bayes in pure Python (standard library only, no new dependency, no language model). One model per
workspace (a person's private space or one organisation -- never shared across workspaces; the caller keeps them apart)
and per feature: the single-value features sender / type / folder are one multi-class model each (the class "" = "none"
is learnt as well, so a document that belongs nowhere stays without a suggestion), tags are one yes/no model per tag.
A model is a plain dict (JSON-serialisable, the caller stores it sealed). Training is incremental: learn() adds one
document, unlearn() takes a corrected one out again -- fast enough to run after every correction.

predict() gives (label, confidence); the caller decides with SURE / MAYBE what is set directly ("automatic") and what
lands as a suggestion in "To review". A label needs MIN_EXAMPLES documents before it is ever predicted."""
import math
import re
import unicodedata

MIN_EXAMPLES = 2      # documents with a label before that label is predicted
MIN_DOCS = 3          # documents in a model before it predicts anything
SURE = 0.85           # confidence from which a value is set directly
MAYBE = 0.55          # ... from which it is offered as a suggestion
MAX_TOKENS = 1500     # distinct words of one document used
MAX_VOCAB = 6000      # words kept per class (the rarest go first when a class grows beyond this)
FEATURES = ("sender", "type", "folder")
_WORD = re.compile(r"[^\W\d_]{3,24}", re.U)
STOP = set("""der die das und oder ein eine einer eines einem einen ist sind war wird werden mit von vom zum zur auf aus
bei für fuer nach nicht auch als bis wie sie ihr ihre ihren ihrem wir uns unser unsere sehr den dem des sich noch nur über
ueber unter durch dass wenn kann können haben hat hatte sein seine seiner bitte vielen dank mfg freundlichen grüßen gruessen
the and for with from that this you your are was were have has not but all our its into been will can per any""".split())
STOP |= {unicodedata.normalize("NFKD", w).encode("ascii", "ignore").decode() for w in STOP}  # the folded forms (für -> fur)


def tokens(text):
    """The distinct, folded words of a text (lower case, without accents, no digits, no stop words)."""
    s = unicodedata.normalize("NFKD", (text or "")[:200_000].lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).replace("ß", "ss")
    out, seen = [], set()
    for w in _WORD.findall(s):
        if w in STOP or w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= MAX_TOKENS:
            break
    return out


def new_model():
    return {"v": 1, "docs": 0, "classes": {}}


def _cls(model, label):
    return model["classes"].setdefault(label, {"n": 0, "w": 0, "t": {}})


def learn(model, toks, label, weight=1):
    """Add a document (its tokens) with label (str; "" = none). weight -1 takes it out again."""
    label = str(label or "")
    c = _cls(model, label)
    c["n"] = max(0, c["n"] + weight)
    model["docs"] = max(0, model.get("docs", 0) + weight)
    t = c["t"]
    for w in toks:
        n = t.get(w, 0) + weight
        if n > 0:
            t[w] = n
        else:
            t.pop(w, None)
    c["w"] = sum(t.values())
    if len(t) > MAX_VOCAB:
        for w, _n in sorted(t.items(), key=lambda kv: kv[1])[:len(t) - MAX_VOCAB]:
            del t[w]
        c["w"] = sum(t.values())
    if c["n"] == 0:
        del model["classes"][label]
    return model


def unlearn(model, toks, label):
    return learn(model, toks, label, -1)


def predict(model, toks):
    """(label, confidence 0..1) of the most likely class, or (None, 0.0) when the model knows too little. The
    confidence is tempered (long documents would otherwise always look certain)."""
    if not model or model.get("docs", 0) < MIN_DOCS:
        return None, 0.0
    classes = {k: v for k, v in model["classes"].items() if v["n"] > 0}
    if len(classes) < 2:
        return None, 0.0
    vocab = set()
    for c in classes.values():
        vocab.update(c["t"])
    known = [w for w in toks if w in vocab]
    if not known:
        return None, 0.0
    total = sum(c["n"] for c in classes.values())
    V = len(vocab) + 1
    scores = {}
    for label, c in classes.items():
        s = math.log(c["n"] / total)
        denom = c["w"] + V
        t = c["t"]
        for w in known:
            s += math.log((t.get(w, 0) + 1) / denom)
        scores[label] = s
    temp = max(1.0, len(known) / 8.0)
    top = max(scores.values())
    ex = {k: math.exp((v - top) / temp) for k, v in scores.items()}
    z = sum(ex.values())
    label = max(ex, key=ex.get)
    conf = ex[label] / z
    if classes[label]["n"] < MIN_EXAMPLES and label != "":
        return None, 0.0
    return label, conf


def tag_model(models, tag):
    return models.setdefault(tag, new_model())


def learn_tags(models, toks, tags, all_tags, weight=1):
    """Tags are yes/no per tag: every known tag learns this document as "1" (has it) or "0" (has not)."""
    tags = set(tags or ())
    for tag in set(all_tags or ()) | tags:
        learn(tag_model(models, tag), toks, "1" if tag in tags else "0", weight)
    return models


def predict_tags(models, toks):
    """[(tag, confidence)] of the tags the models say yes to (confidence >= MAYBE)."""
    out = []
    for tag, m in (models or {}).items():
        label, conf = predict(m, toks)
        if label == "1" and conf >= MAYBE:
            out.append((tag, conf))
    return sorted(out, key=lambda x: -x[1])
