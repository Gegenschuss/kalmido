#!/usr/bin/env python3
"""2.450.0 (#3769): the reference starter speaks the agent's language: the table is complete for every language of the app,
the card check and yes / no work in all of them, and status texts go out as a key with the text as fallback, also towards a
server that has no key yet. Pure Python, no container."""
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kt import FAILS, OKS, check  # noqa: E402

spec = importlib.util.spec_from_file_location("agent_run", os.path.join(HERE, "..", "mcp", "agent_run.py"))
ar = importlib.util.module_from_spec(spec)
sys.modules["agent_run"] = ar
spec.loader.exec_module(ar)

LANGS = ("de", "en", "es", "fr", "it", "nl")
check(tuple(sorted(ar.LANG_NAMES)) == LANGS, "the languages of the app")
for k, forms in ar.TEXTS.items():
    check(tuple(sorted(forms)) == LANGS and all(forms.values()), f"{k}: every language, none empty")
    ph = sorted(re.findall(r"\{\d\}", forms["en"]))
    check(all(sorted(re.findall(r"\{\d\}", v)) == ph for v in forms.values()), f"{k}: the same placeholders")
    if k not in ("no", "why_size", "next", "status_chat") and "{" not in k:
        check(any(v != forms["en"] for lg, v in forms.items() if lg != "en"), f"{k}: translated")
check(ar.say("perm_text", "de", "x") == "**Darf ich das ausführen?** (x)", "German permission question")
check(ar.say("perm_text", "pt", "x") == ar.say("perm_text", "en", "x") == "**May I run this?** (x)", "a language without texts: English")
check(ar.say("perm_text", "", "x").startswith("**May I"), "no language: English")
check(ar.say("nothing-here", "de") == "nothing-here", "an unknown key stays as it is")
os.environ["KALMIDO_PERM_TEXT"] = "Darf es? ({0})"
check(ar.say("perm_text", "fr", "x") == "Darf es? (x)", "the variable overrides every language")
del os.environ["KALMIDO_PERM_TEXT"]
check(all(ar.TEXT_ENV[k] and k in ar.TEXTS for k in ar.TEXT_ENV), "every variable names a text")
check(ar.suggest_line(["A"], "de") == "Weiter: 1) A" and ar.suggest_line(["A"]) == "Next: 1) A", "the suggestion line")

# ---- the card check: the regression of #3769 was that it knew only de / en
ASKS = {"fr": ["Dois-je déployer maintenant ?", "Je propose de garder les deux.", "Veux-tu la variante B ?", "Ma recommandation : la B"],
        "es": ["¿Quieres la variante B?", "Sugiero mantener ambas.", "¿Debo publicarlo ahora?", "Mi propuesta: la B"],
        "it": ["Vuoi la variante B?", "Suggerisco di tenerle entrambe.", "Devo pubblicarlo adesso?", "La mia proposta: la B"],
        "nl": ["Zal ik het nu uitrollen?", "Ik stel voor om beide te houden.", "Wil je variant B?", "Mijn voorstel: B"]}
for lang, lines in ASKS.items():
    for t in lines:
        got = ar.asks_without_card("Fatto.\n" + t, lang)  # "variante B" fits several languages: the agent's wins
        check(got == (t, lang), f"{lang} asks: {t!r} -> {got}")
    check("_" in ar.say("card_hint", lang) and ar.say("card_hint", lang) != ar.say("card_hint", "en"), f"{lang}: its own hint")
for t in ("Déployé, tout est vert.", "Hecho, todo en verde.", "Fatto, tutto verde.", "Klaar, alles is groen.", "```\nje propose\n```",
          "> Ik stel voor", "La carte Je propose est déjà là."):
    check(ar.asks_without_card(t) == ("", ""), f"no ask: {t!r}")
check(ar.asks_without_card("Propongo la B.", "it")[1] == "it" and ar.asks_without_card("Propongo la B.", "es")[1] == "es",
      "one word in two languages: the agent's language wins")
check(ar.asks_without_card("Shall I add it?")[1] == "en" and ar.asks_without_card("Soll ich das einplanen?")[1] == "de", "de / en as before")


class Run(ar.Runner):
    def __init__(self, lang):  # only what the card check needs
        self.agent = {"lang": lang}


r = Run("fr")
body, appr, _ = r.check_approval([], 5, "Dois-je le faire ?", None, [], None, "status_chat")
check(appr is None and "Note du lanceur" in body, f"the visible hint comes in French: {body!r}")

# ---- yes / no: the question now says it in the person's language, so these words have to count
for w in ("oui", "sí", "si", "sì", "ja"):
    check(w in ar.YES_WORDS and w not in ar.NO_WORDS, f"yes: {w}")
for w in ("non", "nee", "nein", "no"):
    check(w in ar.NO_WORDS and w not in ar.YES_WORDS, f"no: {w}")


# ---- status: key plus text; an older server is asked again without the key
class Api(ar.Api):
    def __init__(self, keyless):
        super().__init__("http://x", "t")
        self.keyless, self.puts = keyless, []

    def soft(self, method, path, body=None, timeout=20):
        self.puts.append(dict(body))
        return 400 if self.keyless and "text_key" in body else 200


a = Api(False)
a.status("paused", "Tarifgrenze erreicht", key="status_plan_limit", at="2026-11-02T08:00:00Z")
check(a.puts == [{"status": "paused", "text": "Tarifgrenze erreicht", "text_key": "status_plan_limit", "text_at": "2026-11-02T08:00:00Z"}] and a.key_ok,
      f"key, time and text together: {a.puts}")
a = Api(True)
a.status("working", "Antwortet im Chat", key="status_chat")
check(a.puts[-1] == {"status": "working", "text": "Antwortet im Chat"} and a.key_ok is False, f"an older server: the text goes through {a.puts}")
n = len(a.puts)
a.status("idle", "x", key="status_chat")
check(len(a.puts) == n + 1 and "text_key" not in a.puts[-1], "switched off once: no second try")
a = Api(False)
a.soft = lambda *x, **k: 400
a.status("working", "x", key="status_chat")
check(a.key_ok is None, "a 400 that also comes without the key does not switch it off")
a = Api(True)
a.status("working", "x", host={"model": "Opus 5.5", "permission_fixed": True}, key="status_chat")
check(a.key_ok is False and a.host_ok and a.puts[-1].get("model") == "Opus 5.5" and "text_key" not in a.puts[-1],
      f"host info survives an older server without keys: {a.puts}")


class Sink:
    calls = []

    def status(self, *x, **k):
        self.calls.append((x, k))


r = Run("nl")
r.api = Sink()
r.status_say("paused", "status_plan_limit", at="2026-11-02T08:00:00Z", show="2026-11-02 09:00")
check(r.api.calls[-1] == (("paused", "Limiet van het abonnement bereikt, terug om 2026-11-02 09:00"), {"key": "status_plan_limit", "at": "2026-11-02T08:00:00Z"}),
      f"the fallback in the agent's language: {r.api.calls[-1]}")

# ---- the app knows every status key of the starter, in every language
ROOT = os.path.join(HERE, "..")
with open(os.path.join(ROOT, "static", "js", "agents.js"), encoding="utf-8") as f:
    js = f.read()
tab = dict(re.findall(r"(status_[a-z_]+): N_\('([^']+)'\)", js))
check(set(tab) == {k for k in ar.TEXTS if k.startswith("status_")}, f"client table = starter table: {sorted(tab)}")
for k, en in tab.items():
    check(en == ar.TEXTS[k]["en"], f"{k}: same English text")
    for lg in LANGS:
        if lg != "en":
            with open(os.path.join(ROOT, "static", "i18n", lg + ".json"), encoding="utf-8") as f:
                check(json.load(f).get(en) == ar.TEXTS[k][lg], f"{k}: {lg} file = table")

print(f"p2450_c_starter_lang: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
