// 2.207.0 B (#2763): the HTML of the local page (no script; light / dark from the system, one accent like Kalmido).
package main

const pageHTML = `<!doctype html>
<html lang="{{.L}}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{{if .Reload}}<meta http-equiv="refresh" content="4;url={{.Base}}">{{else if eq .Page "status"}}<meta http-equiv="refresh" content="10">{{end}}
<title>{{t .L "app"}}</title>
<style>
:root{--bg:#ffffff;--bg2:#f8f8f9;--bg3:#efeff1;--line:#e3e3e6;--text:#131418;--text2:#464951;--muted:#60636c;--accent:#6d4bd8;--accent-ink:#ffffff;--ok:#2f9e44;--wait:#8a6200;--err:#b3372f;color-scheme:light}
@media (prefers-color-scheme: dark){:root{--bg:#0f1012;--bg2:#16171a;--bg3:#1e2024;--line:#2a2c31;--text:#eeeef0;--text2:#b8bbc2;--muted:#9497a0;--accent:#a78bfa;--accent-ink:#1a1033;--ok:#51cf66;--wait:#d6a54a;--err:#ef7068;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:0.9375rem/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:46rem;margin:0 auto;padding:2rem 1.25rem 3rem}
header{display:flex;align-items:center;gap:.75rem;margin-bottom:1.5rem}
.mark{width:2rem;height:2rem;border-radius:.5rem;background:var(--accent);flex:none}
h1{font-size:1.25rem;margin:0;font-weight:650}
h2{font-size:1.0625rem;margin:0 0 .25rem;font-weight:600}
h3{font-size:.8125rem;margin:1rem 0 .375rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
p{margin:.25rem 0 .75rem}
.card{background:var(--bg2);border:1px solid var(--line);border-radius:.75rem;padding:1.125rem 1.25rem;margin:0 0 1rem}
.meta{color:var(--text2);font-size:.875rem;word-break:break-all}
.muted{color:var(--muted);font-size:.8125rem}
.state{display:inline-flex;align-items:center;gap:.375rem;font-size:.8125rem;font-weight:600;padding:.125rem .625rem;border-radius:1rem;background:var(--bg3)}
.state::before{content:"";width:.5rem;height:.5rem;border-radius:50%;background:currentColor}
.s-ready{color:var(--ok)}.s-offline,.s-blocked{color:var(--wait)}.s-paused,.s-nodir{color:var(--err)}
.alert{border-left:.1875rem solid var(--err);padding:.5rem .75rem;background:var(--bg3);border-radius:.375rem;margin:.5rem 0}
.notice{border-left:.1875rem solid var(--accent);padding:.5rem .75rem;background:var(--bg2);border-radius:.375rem;margin:0 0 1rem}
ul{list-style:none;margin:0;padding:0}
li{display:flex;justify-content:space-between;gap:1rem;padding:.3125rem 0;border-top:1px solid var(--line);font-size:.875rem}
li:first-child{border-top:0}
.ok{color:var(--ok)}.bad{color:var(--err)}
.row{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:.875rem}
form{margin:0;display:inline}
button,.btn{font:inherit;font-size:.875rem;border:1px solid var(--line);background:var(--bg);color:var(--text);padding:.4375rem .875rem;border-radius:.5rem;cursor:pointer;text-decoration:none;display:inline-block}
button:hover,.btn:hover{border-color:var(--muted)}
.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);font-weight:600}
.primary:hover{border-color:var(--accent);filter:brightness(1.06)}
.danger{color:var(--err)}
label{display:block;font-weight:600;font-size:.875rem;margin:.75rem 0 .25rem}
textarea,input[type=text]{width:100%;font:inherit;font-size:.875rem;color:var(--text);background:var(--bg);border:1px solid var(--line);border-radius:.5rem;padding:.5rem .625rem}
textarea{min-height:5rem;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;word-break:break-all}
textarea:focus,input:focus{outline:.125rem solid var(--accent);outline-offset:0;border-color:var(--accent)}
.check{display:flex;gap:.5rem;align-items:center;font-weight:400;margin-top:1rem}
dl{display:grid;grid-template-columns:auto 1fr;gap:.25rem 1rem;margin:.5rem 0 0;font-size:.875rem}
dt{color:var(--muted)}dd{margin:0;word-break:break-all}
footer{margin-top:2rem;color:var(--muted);font-size:.8125rem}
footer p{margin:.125rem 0}
</style></head><body><main>
<header><div class="mark"></div><h1>{{t .L "app"}}</h1></header>
{{if .Notice}}<div class="notice">{{.Notice}}</div>{{end}}

{{if eq .Page "status"}}
  {{range .Inboxes}}{{$v := .}}
  <section class="card">
    <div style="display:flex;justify-content:space-between;gap:1rem;align-items:baseline;flex-wrap:wrap">
      <h2>{{.In.Name}}</h2>
      <span class="state s-{{.State}}">{{t $.L (printf "st_%s" .State)}}</span>
    </div>
    <dl><dt>{{t $.L "folder"}}</dt><dd>{{.In.Folder}}</dd><dt>{{t $.L "target"}}</dt><dd>{{.In.Target}}</dd></dl>
    {{if eq .State "paused"}}<div class="alert">{{t $.L "paused_hint"}}{{if .Msg}} ({{.Msg}}){{end}}</div>
    {{else if or (eq .State "offline") (eq .State "blocked")}}<div class="alert">{{.Msg}}{{if future .Next}} {{t $.L "next_try" (clock .Next)}}{{end}}</div>
    {{else if eq .State "nodir"}}<div class="alert">{{t $.L "st_nodir"}}: {{.In.Folder}}</div>{{end}}
    <h3>{{t $.L "waiting"}}</h3>
    {{if .Waiting}}<ul>{{range .Waiting}}<li><span>{{.}}</span></li>{{end}}</ul>{{else}}<p class="muted">{{t $.L "none_waiting"}}</p>{{end}}
    <h3>{{t $.L "recent"}}</h3>
    {{if .Events}}<ul>{{range .Events}}<li><span>{{.File}}</span><span class="{{if .OK}}ok{{else}}bad{{end}}">{{evtext $.L $v.In .}} · {{when .At}}</span></li>{{end}}</ul>{{else}}<p class="muted">{{t $.L "none_recent"}}</p>{{end}}
    <div class="row">
      <form method="post" action="{{$.Base}}open"><input type="hidden" name="t" value="{{$.T}}"><input type="hidden" name="id" value="{{.In.ID}}"><button>{{t $.L "btn_open"}}</button></form>
      <form method="post" action="{{$.Base}}retry"><input type="hidden" name="t" value="{{$.T}}"><input type="hidden" name="id" value="{{.In.ID}}"><button>{{t $.L "btn_retry"}}</button></form>
      <a class="btn danger" href="{{$.Base}}remove?id={{.In.ID}}">{{t $.L "btn_remove"}}</a>
    </div>
  </section>
  {{end}}
  <div class="row" style="margin-bottom:1.25rem"><a class="btn primary" href="{{.Base}}add">{{t .L "btn_add"}}</a></div>
  <section class="card">
    <h2>{{t .L "autostart"}}</h2>
    <p class="meta">{{if and .AutoOn .Installed}}{{t .L "run_bg"}}{{else}}{{t .L "run_fg"}}{{end}}</p>
    <div class="row">
      {{if not .AutoOn}}<form method="post" action="{{.Base}}autostart"><input type="hidden" name="t" value="{{.T}}"><input type="hidden" name="on" value="1"><button class="primary">{{t .L "btn_as_on"}}</button></form>
      {{else}}{{if not .Installed}}<form method="post" action="{{.Base}}autostart"><input type="hidden" name="t" value="{{.T}}"><input type="hidden" name="on" value="1"><button class="primary">{{t .L "btn_as_take"}}</button></form>{{end}}
      <form method="post" action="{{.Base}}autostart"><input type="hidden" name="t" value="{{.T}}"><input type="hidden" name="on" value="0"><button>{{t .L "btn_as_off"}}</button></form>{{end}}
      <form method="post" action="{{.Base}}quit"><input type="hidden" name="t" value="{{.T}}"><button>{{t .L "btn_quit"}}</button></form>
      <a class="btn danger" href="{{.Base}}uninstall">{{t .L "btn_uninstall"}}</a>
    </div>
  </section>

{{else if eq .Page "add"}}
  <section class="card">
    <h2>{{t .L "add_title"}}</h2>
    {{if .Error}}<div class="alert">{{.Error}}</div>{{end}}
    {{if not .Step2}}
    <p class="meta">{{t .L "add_intro"}}</p>
    <form method="post" action="{{.Base}}check" style="display:block">
      <input type="hidden" name="t" value="{{.T}}">
      <label for="code">{{t .L "code"}}</label>
      <textarea id="code" name="code" required autofocus spellcheck="false" autocomplete="off" placeholder="kalmido-scan:1:…">{{.Code}}</textarea>
      <div class="row"><button class="primary">{{t .L "btn_check"}}</button><a class="btn" href="{{.Base}}?n=x">{{t .L "btn_cancel"}}</a></div>
    </form>
    {{else}}
    <dl><dt>{{t .L "inbox"}}</dt><dd>{{.InboxName}}</dd><dt>{{t .L "target"}}</dt><dd>{{.Target}}</dd></dl>
    <form method="post" action="{{.Base}}save" style="display:block">
      <input type="hidden" name="t" value="{{.T}}"><input type="hidden" name="code" value="{{.Code}}">
      <label for="folder">{{t .L "folder_here"}}</label>
      <input type="text" id="folder" name="folder" value="{{.Folder}}" required spellcheck="false" autocomplete="off">
      <p class="muted">{{t .L "folder_hint" .UpDir}}{{if .Mac}} {{t .L "folder_hint_mac"}}{{end}}</p>
      <label class="check"><input type="checkbox" name="autostart" value="1"{{if .Autostart}} checked{{end}}> {{t .L "as_check"}}</label>
      <div class="row"><button class="primary">{{t .L "btn_save"}}</button><a class="btn" href="{{.Base}}?n=x">{{t .L "btn_cancel"}}</a></div>
    </form>
    {{end}}
  </section>

{{else if eq .Page "confirm"}}
  <section class="card">
    <p>{{.Question}}</p>
    <div class="row">
      <form method="post" action="{{.Base}}{{.Action}}"><input type="hidden" name="t" value="{{.T}}">{{if .ID}}<input type="hidden" name="id" value="{{.ID}}">{{end}}<button class="primary">{{.Button}}</button></form>
      <a class="btn" href="{{.Base}}?n=x">{{t .L "btn_cancel"}}</a>
    </div>
  </section>

{{else}}
  <section class="card"><p>{{.Message}}</p></section>
{{end}}
<footer><p>{{t .L "version" .Version}}</p><p>{{t .L "settings_at" .Dir}}</p></footer>
</main></body></html>`
