# Book Translator

Translate a whole PDF book into **Arabic**, **French**, or **English** — page by page,
with the original images kept, an RTL layout for Arabic, and the original page numbers.

<img src="book_trans.ico" width="48">

## What it does

- Translates the **full text of each page** (not a summary — the app detects and
  auto-retries refusals/summaries).
- Keeps every original image, cropped to its position on the page.
- Renders Arabic right-to-left with a proper Arabic font; French/English left-to-right.
- Produces a new PDF named after your chosen Title (e.g. `Red Rising UV1.pdf`).
- **Runs extend the same output PDF cumulatively** — run pages `1-40` tonight, then
  `41-80` tomorrow; the PDF grows and translated pages are skipped automatically.
- Sends **only the extracted page text** (plus a name glossary and a short style
  reference) to the model. The PDF file, its images, and its metadata are never sent.
- A **name glossary** is built once per book and language, then cached in
  `<output>.pdf.glossary.json` — later runs reuse it with **zero** extra requests,
  and NVIDIA/custom models get the same names Gemini used.

## Quick start (Windows EXE)

1. Run `dist\BookTranslator.exe`.
2. Click **Connect…** next to _Backend_ and paste an API key (see below).
3. Drag a PDF into the window (or **Browse**), pick Language / Model / Title.
4. Leave _Pages_ empty to translate the whole book, then click **Translate**.
5. The PDF is saved when the run finishes — or at any time with **Stop & Save**.

Keys can also live in a `.env` file next to the EXE (`dist\.env`). The **Connect…**
button writes there for you, and rebuilds of the EXE keep that file untouched.

## Models — which one to pick

| Model                            | Quality | Quota              | Notes                                                                               |
| -------------------------------- | ------- | ------------------ | ----------------------------------------------------------------------------------- |
| `gemini-3-flash-preview`         | ★ best  | free tier, limited | Best free results for Arabic fiction prose                                          |
| `gemini-3.8-flash`               | ★ best  | free tier, **low** | Same family; quotas differ per account                                              |
| `gemini-flash-lite-latest`       | good    | larger             | Fast and usually more daily quota, but the **meaning can be weaker** on dense prose |
| `gemini-2.5-flash`               | good    | medium             | Previous generation, dependable                                                     |
| `meta/muse-glimmer-30b` (NVIDIA) | good    | **much larger**    | Can take several minutes per page — start it and leave it running                   |
| _custom_                         | depends | your provider      | Any OpenAI-compatible API (see below)                                               |

**If you're on the free tier: use Gemini 3 Flash (`gemini-3-flash-preview`) or
`gemini-3.8-flash` for better results.** If you need more quota, Flash Lite latest
translates well and has more room, but check the meaning on a few pages. The NVIDIA
model is comparable to Lite with **much more quota** — sacrifice speed, not the
wallet.

### Keys

| Backend | Key                                    | Where to get it                                                         |
| ------- | -------------------------------------- | ----------------------------------------------------------------------- |
| Gemini  | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | [aistudio.google.com](https://aistudio.google.com) → Get API key (free) |
| NVIDIA  | `NVIDIA_API_KEY`                       | [build.nvidia.com](https://build.nvidia.com) → free developer key       |
| Custom  | `CUSTOM_API_KEY`                       | your provider                                                           |

Use the **Connect…** button or edit `.env`:

```env
GEMINI_API_KEY=...
NVIDIA_API_KEY=...
CUSTOM_BASE_URL=https://api.openai.com/v1
CUSTOM_API_KEY=...
```

## Custom backend (bring your own model)

Pick _custom_ in the Backend list, click **Connect…**, and enter:

- **API base URL** — any OpenAI-compatible endpoint, e.g.
  `https://api.openai.com/v1`,
  `https://openrouter.ai/api/v1`,
  `https://api.groq.com/openai/v1`,
  `https://api.deepseek.com/v1`,
  `http://localhost:11434/v1` (Ollama, no key needed).
- **API key** — leave empty for local servers that don't need one.

Then type the **model id** (e.g. `gpt-4o-mini`, `deepseek-chat`, `llama3.3`) in the
Model field and run. The app calls `<base URL>/chat/completions` with the standard
chat-completions payload, so anything that speaks that dialect works.

## Pages, runs, and what gets saved

- **Pages** syntax: `40` (one page), `1-40`, `40,60-62`, or empty for the whole book.
- **Redo selected pages (force)**: re-translates pages you typed even if they were
  already done (normally saved pages are skipped).
- **Extra context (optional)**: when checked, a short continuity note (characters,
  key events, terms, tone) of the pages before your range is built from the source
  text and cached in `<output>.pdf.context.json`. Each later run extends it with
  **one request**, or reuses it with **zero**; translation is still one request per
  page. Useful when resuming mid-book or switching models — leave it off to save quota.
- **Stop & Save**: stops the run and merges everything translated so far into the PDF.
  Re-run later to continue where you stopped.
- **Cancel**: stops and saves **nothing** — the PDF and saved progress are restored
  exactly as they were before the run.
- Progress is stored in `<output>.pdf.progress.jsonl`. Deleting it re-translates
  everything; keeping it lets runs resume quickly.
- If the output PDF is open in a viewer when the run finishes, the app stops and
  warns you first: **close the file, then click OK** and the PDF is saved to the
  same name — or **click OK without closing it** and a `..._2.pdf` copy is created
  instead.

## Troubleshooting

- **"Daily quota reached"** — the model's free daily quota is used up. Translated
  pages are already merged into the PDF; re-run after the quota resets and the app
  continues automatically.
- **NVIDIA 504 / Gateway Timeout / very slow** — normal for the free NIM tier; the
  app retries automatically. Prefer other models for quick tests.
- **`..._2.pdf` created** — you clicked OK on the "PDF is open" warning without
  closing the target PDF. Close it and click **Save** (or re-run) to update the
  original; progress is kept, so it's fast. Otherwise just use the `_2` copy.
- **"No … key"** — click **Connect…** and paste a key, or add it to `.env`.
- **A page looks like a summary** — it was kept because no clean translation existed;
  re-run that page range (or leave it selected) and the app will retry it.

## Running from source / building the EXE

```bash
pip install -r requirements.txt
python app.py            # run the GUI from source

build_exe.bat            # build dist\BookTranslator.exe (PyInstaller onefile)
```

Requires Python 3.10+. The build script preserves `dist\.env` between builds.

## Legal

Translate only books you legally own, for personal use. Model providers' terms apply
to the requests sent from your own API key.
