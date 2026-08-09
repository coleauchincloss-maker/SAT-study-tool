// Bring-your-own questions: paste or upload your own set, preview how it
// parses, then import it into a separate pool a duel can specifically draw
// from. No LLM, no scraping — the caller supplies the answer key, so only
// structural checks apply (four distinct choices, a real answer, no dupes).

import { esc } from '../components/ui.js';
import { topNav } from '../components/nav.js';
import * as net from '../net.js';
import { parse, validateForPreview } from '../importParse.js';

const SAMPLE = `Q: A café sells muffins for $3 each and a loyalty card costs $12. If Priya spent $33 total using her loyalty card, how many muffins did she buy?
A) 6
B) 7
C) 8
D) 9
ANSWER: B
EXPLANATION: 33 - 12 = 21 spent on muffins; 21 / 3 = 7 muffins.
DOMAIN: Algebra
SECTION: math
---
Q: In the passage, the word "unassuming" most nearly means
A) boastful
B) modest and unpretentious
C) hostile
D) indecisive
ANSWER: B
DOMAIN: Craft & Structure
SECTION: rw`;

let format = 'text'; // 'text' | 'json' | 'csv'
let defaultSection = 'math';
let rawText = '';
let preview = null; // { rows: [{q, problems}], validCount }
let importResult = null; // server report or { error }
let importedList = null; // { count, questions } from server
let busy = false;

function currentText(root) {
  return root?.querySelector('#import-text')?.value ?? rawText;
}

function buildPreview(text) {
  const { questions, errors } = parse(format, text);
  const rows = questions.map((q) => ({ q, problems: validateForPreview(q, defaultSection) }));
  return { rows, parseErrors: errors, validCount: rows.filter((r) => r.problems.length === 0).length };
}

export function renderImport(root, { actions, lobby }) {
  if (importedList === null) {
    importedList = { count: 0, questions: [] };
    net.fetchImportedQuestions().then((data) => {
      importedList = data;
      renderImport(root, { actions, lobby });
    });
  }

  const formatTabs = [
    { id: 'text', label: 'Plain text' },
    { id: 'json', label: 'JSON' },
    { id: 'csv', label: 'CSV' },
  ]
    .map((f) => `<button type="button" class="format-tab ${format === f.id ? 'is-on' : ''}" data-action="format" data-format="${f.id}">${esc(f.label)}</button>`)
    .join('');

  const formatHelp = {
    text: `
      <ul class="import-field-list">
        <li><code>Q:</code> <span>the question text</span></li>
        <li><code>A)</code>–<code>D)</code> <span>the four answer choices, one per line</span></li>
        <li><code>ANSWER:</code> <span>which letter is correct — A, B, C, or D <em>(required)</em></span></li>
        <li><code>EXPLANATION:</code> <span>why that's the answer <em>(optional)</em></span></li>
        <li><code>DOMAIN:</code> <span>e.g. "Algebra" or "Craft & Structure" <em>(optional)</em></span></li>
        <li><code>SECTION:</code> <span><code>math</code> or <code>rw</code> <em>(optional — falls back to the picker on the right)</em></span></li>
      </ul>
      <p class="card-sub">Put a line of <code>---</code> between each question. That's the whole format — the sample below shows two questions end to end.</p>`,
    json: `
      <p class="card-sub">An array of question objects, or <code>{"questions": [...]}</code>.</p>
      <ul class="import-field-list">
        <li><code>prompt</code> <span>the question text <em>(required)</em></span></li>
        <li><code>choices</code> <span>an array of exactly 4 answer strings <em>(required)</em></span></li>
        <li><code>answer</code> <span>which one is correct — 0, 1, 2, 3, or a letter <em>(required)</em></span></li>
        <li><code>section</code> <span><code>"math"</code> or <code>"rw"</code> <em>(optional)</em></span></li>
        <li><code>domain</code>, <code>explanation</code> <span><em>(optional)</em></span></li>
      </ul>`,
    csv: `
      <p class="card-sub">First row must be exactly this header:</p>
      <pre class="import-csv-header">prompt,choice1,choice2,choice3,choice4,answer,explanation,domain,section,skill,difficulty</pre>
      <p class="card-sub">Column <em>order</em> doesn't matter as long as the header names match; any extra columns beyond these are just ignored.</p>`,
  }[format];

  const previewBlock = preview
    ? `
      <div class="import-preview">
        <p class="card-sub">
          <strong>${preview.validCount} of ${preview.rows.length}</strong> parsed as valid questions.
          ${preview.parseErrors.length ? ` ${preview.parseErrors.length} parse issue(s) below.` : ''}
        </p>
        ${preview.parseErrors.length ? `<ul class="import-errors">${preview.parseErrors.map((e) => `<li>${esc(e)}</li>`).join('')}</ul>` : ''}
        <ul class="import-rows">
          ${preview.rows
            .slice(0, 50)
            .map(
              (r) => `
              <li class="${r.problems.length ? 'is-bad' : 'is-good'}">
                <span class="import-row-status">${r.problems.length ? '✗' : '✓'}</span>
                <span class="import-row-body">
                  <span class="import-row-prompt">${esc((r.q.prompt || '(no prompt)').slice(0, 100))}</span>
                  ${r.problems.length ? `<span class="import-row-issues">${esc(r.problems.join('; '))}</span>` : `<span class="import-row-issues is-ok">${esc(r.q.domain || defaultSection)}</span>`}
                </span>
              </li>`,
            )
            .join('')}
          ${preview.rows.length > 50 ? `<li class="import-more">…and ${preview.rows.length - 50} more.</li>` : ''}
        </ul>
        <button class="btn btn-primary btn-block" data-action="import" ${preview.validCount === 0 || busy ? 'disabled' : ''}>
          ${busy ? 'Importing…' : `Import ${preview.validCount} question${preview.validCount === 1 ? '' : 's'}`}
        </button>
      </div>`
    : '';

  const resultBlock = importResult
    ? importResult.error
      ? `<p class="vs-notice is-bad">${esc(importResult.error)}</p>`
      : `<p class="vs-notice ${importResult.accepted ? '' : 'is-bad'}">
           Imported ${importResult.accepted ?? 0} of ${importResult.requested ?? 0}.
           ${importResult.rejected?.length ? ` ${importResult.rejected.length} rejected: ${esc(importResult.rejected.slice(0, 3).map((r) => r.reason).join('; '))}${importResult.rejected.length > 3 ? '…' : ''}` : ''}
         </p>`
    : '';

  root.innerHTML = `
    <div class="wrap">
      ${topNav({ active: 'import', name: lobby?.name ?? '' })}

      <h1 class="page-hero">Bring your own questions.</h1>
      <p class="page-hero-sub">Paste or upload a set you have the rights to use, then duel on exactly those questions.</p>

      <section class="card vs-offline" style="border-color:#5b3fd655; background:#5b3fd60d; margin-bottom:20px;">
        <strong>A note on sources</strong>
        <p class="card-sub">
          Real College Board SAT questions are copyrighted — this importer doesn't scrape or auto-extract them from
          anywhere, including official PDFs or Bluebook. Bring questions you wrote yourself, or content you already
          have the rights to reuse. You're responsible for what you paste in.
        </p>
      </section>

      <div class="grid">
        <section class="card col-8">
          <h2>1. Paste or upload</h2>
          <p class="card-sub">Pick a format below, then either type/paste your questions in the box, or use a file. Click <strong>Preview</strong> to check them before anything is imported.</p>
          <div class="format-tabs">${formatTabs}</div>
          <div class="import-format-help">${formatHelp}</div>

          <textarea id="import-text" class="import-textarea" rows="14" placeholder="${format === 'text' ? esc(SAMPLE) : 'Paste your questions here…'}">${esc(rawText)}</textarea>

          <div class="field-row" style="margin-top:10px;">
            <label>
              <span>File instead (.txt, .json, .csv)</span>
              <input type="file" accept=".txt,.json,.csv" data-action="file" />
            </label>
            <label>
              <span>Default section (if a question doesn't specify one)</span>
              <select data-action="default-section">
                <option value="math" ${defaultSection === 'math' ? 'selected' : ''}>Math</option>
                <option value="rw" ${defaultSection === 'rw' ? 'selected' : ''}>Reading &amp; Writing</option>
              </select>
            </label>
          </div>

          <div style="display:flex; gap:10px; margin-top:6px;">
            <button class="btn btn-ghost" data-action="load-sample">Load a sample</button>
            <button class="btn btn-primary" data-action="preview">Preview</button>
          </div>

          ${previewBlock}
          ${resultBlock}
        </section>

        <section class="card col-4">
          <h2>Your imported bank</h2>
          <p class="card-sub"><strong>${importedList.count}</strong> question${importedList.count === 1 ? '' : 's'} imported.</p>
          ${importedList.count
            ? `<ul class="import-bank-list">
                 ${importedList.questions.slice(0, 12).map((q) => `<li><span class="pill pill-${q.section}">${q.section === 'math' ? 'Math' : 'R&W'}</span> ${esc(q.prompt)}</li>`).join('')}
                 ${importedList.count > 12 ? `<li class="import-more">…and ${importedList.count - 12} more.</li>` : ''}
               </ul>
               <button class="btn btn-quiet btn-block" data-action="clear">Clear all imported questions</button>`
            : '<p class="empty">Nothing imported yet. Once you do, "My imported questions" shows up as a question set on the Duel page.</p>'}
        </section>
      </div>

      <footer class="foot">
        Imported questions are stored on this match server (not this browser), so they're available to whoever
        joins a duel on this server — the same as the built-in bank.
      </footer>
    </div>`;

  root.oninput = (event) => {
    if (event.target.id === 'import-text') rawText = event.target.value;
  };

  root.onclick = async (event) => {
    const button = event.target.closest('[data-action]');
    if (!button) return;
    const { action } = button.dataset;

    if (action === 'navigate') return actions.navigate(button.dataset.route);

    if (action === 'format') {
      rawText = currentText(root);
      format = button.dataset.format;
      preview = null;
      return renderImport(root, { actions, lobby });
    }

    if (action === 'load-sample') {
      rawText = SAMPLE;
      format = 'text';
      preview = null;
      return renderImport(root, { actions, lobby });
    }

    if (action === 'preview') {
      rawText = currentText(root);
      preview = buildPreview(rawText);
      importResult = null;
      return renderImport(root, { actions, lobby });
    }

    if (action === 'import') {
      const valid = preview.rows.filter((r) => r.problems.length === 0).map((r) => ({ ...r.q, section: r.q.section || defaultSection }));
      busy = true;
      renderImport(root, { actions, lobby });
      try {
        importResult = await net.importQuestions(valid);
        importedList = await net.fetchImportedQuestions();
        preview = null;
      } catch (error) {
        importResult = { error: error.message };
      }
      busy = false;
      return renderImport(root, { actions, lobby });
    }

    if (action === 'clear') {
      if (!window.confirm('Delete every imported question from this server? This cannot be undone.')) return;
      await net.clearImportedQuestions();
      importedList = await net.fetchImportedQuestions();
      return renderImport(root, { actions, lobby });
    }
  };

  root.onchange = (event) => {
    if (event.target.dataset.action === 'default-section') {
      defaultSection = event.target.value;
    } else if (event.target.dataset.action === 'file') {
      const file = event.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        rawText = String(reader.result || '');
        if (file.name.endsWith('.json')) format = 'json';
        else if (file.name.endsWith('.csv')) format = 'csv';
        else format = 'text';
        preview = null;
        renderImport(root, { actions, lobby });
      };
      reader.readAsText(file);
    }
  };
}
