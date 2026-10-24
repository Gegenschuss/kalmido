# The built-in assistant

*Since 2.75.0.*

Kalmido can use one language model of the operator's choice for small, everyday helps right inside the app: the
**assistant**. It is **off unless the operator configures it**, and even then every person switches it on for
themselves and decides which lists it may read. Everything it produces is a **proposal**: you accept or reject it; the
assistant never changes anything by itself.

The assistant is the only place where Kalmido itself calls a language model. Your own [agents](AGENTS.md) (Claude Code,
Codex, n8n, a local script) stay what they are: they run where you control them and connect to Kalmido as clients.

## Contents

- [What it does](#what-it-does)
- [What it does not do](#what-it-does-not-do)
- [Switch it on](#switch-it-on)
- [What goes to the model](#what-goes-to-the-model)
- [Log](#log)
- [Built-in assistant or your own agent?](#built-in-assistant-or-your-own-agent)
- [Operators: configuration](#operators-configuration)

## What it does

Six kinds, each started by a tap of the person who uses it:

| Kind | Where | Result |
|------|-------|--------|
| **Summarize** | task panel > Assistant | a short summary of the note and the comments (of an e-mail task: the mail text), in a dialog with *Copy* and *Add as comment* |
| **Draft a reply** | task panel > Assistant | a reply draft following a short instruction ("a short, friendly reply"), same dialog |
| **Extract tasks** | task panel > Assistant | a proposal with new tasks pulled out of the text, for the task's project (or one of your shared projects) |
| **Suggest tags and due date** | task panel > Assistant | a proposal with tags, a due date and a priority for this task |
| **Sort with the assistant** | basket header | a proposal that moves the marked basket items (or the first 30 open ones) into your shared projects |
| **Assistant plan** | Today > "…" | a day plan proposal (planned start and duration) from the tasks of your shared projects |

Proposals open in the same dialog as the proposals of agents (named "Assistant"): tick or untick entries, change them,
*Apply* makes the changes as you in one step, *Undo* takes them back.

## What it does not do

- No long tasks, no programming, no research on the web, no files: for that, set up [your own agent](AGENTS.md).
- It does not act on its own, on a schedule or on events; it only answers when you ask. Sorting the basket every morning
  goes through a planned job of your own agent (2.126.1, Agents > the agent's card > *Plans* > Kind *Sort the basket*, see
  [Planned jobs](AGENTS.md#planned-jobs)): you find its proposal as a card and decide.
- It never changes anything directly: no proposal is applied without your tap.
- Office data (documents, invoices, bookkeeping) is not part of the assistant in 2.75.0.

## Switch it on

Settings > **Assistant** (the section only shows when the operator configured an assistant):

1. *Use the assistant*: on. The line below it says to which provider and host your texts go, and the model.
2. *Projects the assistant may read*: tick the projects it may use. The basket is not in the project: basket items go only when
   you pick them yourself (sort the basket, or the assistant menu of a basket task). Archived projects and health projects
   cannot be ticked. Only projects you own can be ticked (2.148.1): a project someone shared with you holds their notes and
   comments, so only its owner decides whether they go to the assistant. A project ticked earlier that you do not own is
   no longer used.

Children's accounts and agents never get the assistant. Switching it off again hides every entry point at once.

## What goes to the model

- Only the task or the tasks you started it on, and only from a shared project or your own basket. The server checks this
  again on every call; a task of another project is refused.
- Of a task: its title, note and comments (summary, reply draft, extract), or its title, project, tags and dates (tags,
  basket sort, day plan). Locked notes never, health projects never, attachments and files never. Other people appear at
  most with their display name, where a proposal needs it (assignments).
- Long texts are shortened to the operator's limit; the dialog says so.
- Text inside tasks is handed to the model as data, not as instructions; whatever the model answers is checked by the
  server (only known projects and tasks, only the fields a proposal may have) before you see it.

The provider is the one the operator chose. Ask your operator which contract (data processing agreement, no training
on your data) applies.

## Log

Settings > Assistant > *Log* lists every call: time, kind, status (done, error, took too long, refused, shortened) and
duration. Texts are not kept, neither the question nor the answer. Admins see the number of calls and errors per day in
Settings > Administration > Server.

## Built-in assistant or your own agent?

| | Built-in assistant | Your own agent |
|-|--------------------|----------------|
| Set up | operator sets three variables | a program on a computer you control, a token |
| Starts | only on your tap | events, schedules, chat, mentions |
| Sorts the basket every morning | no | yes, as a planned job (a proposal card for you, 2.126.1) |
| Turns table rows into tasks | no | yes, as a proposal you apply (2.126.1) |
| Can | the six kinds above | anything its program can (code, research, long jobs) |
| Sees | projects you share with the assistant | projects shared with the agent (its own member) |
| Changes | only through proposals you apply | through the API, within its permissions |

## Operators: configuration

The assistant talks to any OpenAI-compatible *chat completions* endpoint (a hosted provider or a local server such as
Ollama). It is configured with environment variables only: `KALMIDO_AI_BASE_URL`, `KALMIDO_AI_MODEL`,
`KALMIDO_AI_KEY_FILE` (or `KALMIDO_AI_KEY`), `KALMIDO_AI_NAME`, `KALMIDO_AI_TIMEOUT_S`, `KALMIDO_AI_MAX_CHARS` and
`KALMIDO_AI_MAX_TOKENS`. Without `KALMIDO_AI_BASE_URL` and `KALMIDO_AI_MODEL` the assistant does not exist. What each
variable does, and how to keep the key out of logs and backups, is in
[SELF-HOSTING.md](SELF-HOSTING.md#built-in-assistant). If you run Kalmido for others, add the provider to your list of
sub-processors; [PRIVACY-ASSISTANT-TEMPLATE.md](PRIVACY-ASSISTANT-TEMPLATE.md) has template wording.
