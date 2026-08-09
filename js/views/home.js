// Duel: pick a fight, join one, or fire off a challenge code. Deliberately
// narrow — level/XP/skill stats live on the Dashboard now.

import { esc } from '../components/ui.js';
import { topNav } from '../components/nav.js';
import { myName, rivalList } from '../rivals.js';
import { serverBase } from '../net.js';

/**
 * Self-hosting tools (pointing at a different server, generating fresh
 * questions from an API key you set on your own machine) only make sense
 * when you're running server.py yourself — a friend who just opened a
 * shared deployed link has no use for them and no way to act on them.
 */
function isSelfHosted() {
  const host = location.hostname;
  return (
    host === 'localhost' ||
    host === '127.0.0.1' ||
    /^192\.168\.\d{1,3}\.\d{1,3}$/.test(host) ||
    /^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(host) ||
    /^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$/.test(host)
  );
}

const MODE_META = {
  buzzer: { icon: '⚡', badge: 'MAIN MODE' },
  steal: { icon: '🥊' },
  draft: { icon: '🗺️' },
  wager: { icon: '🎲' },
};
const MODE_ORDER = ['buzzer', 'steal', 'draft', 'wager'];

/**
 * Whether a second device can actually reach this server — the single most
 * common reason a match never starts. Condensed to a one-line status, with the
 * full how-to available on request rather than dominating the page.
 */
function statusLine(info) {
  if (!info) {
    return { ok: false, html: `No match server. Start it with <code>python3 server.py --lan</code> and reload.` };
  }
  if (serverBase()) {
    return { ok: true, html: `Using the match server at <strong>${esc(serverBase())}</strong>.` };
  }
  if (!info.lanBound) {
    return {
      ok: false,
      html: `Only this computer can reach this server — friends can't join yet. Restart with <code>python3 server.py --lan</code>.`,
    };
  }
  return { ok: true, html: `Ready for friends on your Wi-Fi &middot; <a href="${esc(info.lanUrl ?? '')}">${esc(info.lanUrl ?? '')}</a>` };
}

export function renderHome(root, { state, actions, lobby }) {
  const info = lobby.info; // /api/match/info, or null when no server
  const modes = info?.modes ?? {};
  const rivals = rivalList();
  const offline = !info;
  const status = statusLine(info);

  const importedTotal = info?.importedPool?.total ?? 0;
  const orderedModes = MODE_ORDER.map((id) => modes[id]).filter(Boolean);
  const modeGrid = orderedModes
    .map((mode) => {
      const meta = MODE_META[mode.id] ?? { icon: '🎯' };
      const wide = mode.id === 'buzzer';
      return `
      <label class="duel-mode ${wide ? 'is-wide' : 'is-half'} ${lobby.mode === mode.id ? 'is-on' : ''}">
        <input type="radio" name="mode" value="${esc(mode.id)}" ${lobby.mode === mode.id ? 'checked' : ''}
               aria-describedby="mode-blurb-${esc(mode.id)}" />
        <span class="duel-mode-check" aria-hidden="true">✓</span>
        <span class="duel-mode-icon" aria-hidden="true">${meta.icon}</span>
        <span class="duel-mode-body">
          <strong>${esc(mode.label)}${meta.badge ? ` <em class="mode-badge">${meta.badge}</em>` : ''}</strong>
          <span id="mode-blurb-${esc(mode.id)}">${esc(mode.blurb)}</span>
        </span>
      </label>`;
    })
    .join('');

  root.innerHTML = `
    <div class="wrap">
      ${topNav({ active: 'home', name: lobby.name })}

      <h1 class="page-hero">Challenge a friend to an SAT duel.</h1>
      <p class="page-hero-sub">Choose the rules, open your room, and share the four-character code.</p>

      ${offline
        ? `<section class="card vs-offline"><strong>No match server</strong>
             <p class="card-sub">Live duels need the server running. Start it with
               <code>python3 server.py --lan</code> and reload. Challenge codes below still work.</p>
           </section>`
        : ''}

      <div class="grid">
        <section class="card col-8">
          <div class="step">
            <div class="step-num">1</div>
            <div><h3>Who are you?</h3><p class="card-sub">This is what your opponent will see.</p></div>
          </div>
          <label class="sr-only" for="duel-name">Your display name</label>
          <input id="duel-name" class="wide-field" type="text" value="${esc(lobby.name)}" data-field="name"
                 placeholder="Your display name" maxlength="16" />

          <hr class="sep" />

          <div class="step">
            <div class="step-num">2</div>
            <div><h3>Pick your battle</h3><p class="card-sub">Both players receive the same SAT questions.</p></div>
          </div>
          <fieldset class="duel-mode-grid">
            <legend class="sr-only">Match format</legend>
            ${modeGrid || '<p class="empty">Start the server to see the formats.</p>'}
          </fieldset>

          <hr class="sep" />

          <div class="step">
            <div class="step-num">3</div>
            <div><h3>Match settings</h3><p class="card-sub">Tune the rules, the clock, and academic-integrity checks.</p></div>
          </div>

          <div class="field-row">
            <label>
              <span>Question set</span>
              <select data-field="section">
                <option value="" ${lobby.section === '' ? 'selected' : ''}>Math + Reading &amp; Writing</option>
                <option value="math" ${lobby.section === 'math' ? 'selected' : ''}>Math only</option>
                <option value="rw" ${lobby.section === 'rw' ? 'selected' : ''}>Reading &amp; Writing only</option>
              </select>
            </label>
            <label>
              <span>Time per question</span>
              <select data-field="questionSeconds">
                <option value="" ${lobby.questionSeconds === '' ? 'selected' : ''}>Default for this mode</option>
                <option value="15" ${lobby.questionSeconds === '15' ? 'selected' : ''}>15 seconds</option>
                <option value="20" ${lobby.questionSeconds === '20' ? 'selected' : ''}>20 seconds</option>
                <option value="30" ${lobby.questionSeconds === '30' ? 'selected' : ''}>30 seconds</option>
                <option value="45" ${lobby.questionSeconds === '45' ? 'selected' : ''}>45 seconds</option>
                <option value="60" ${lobby.questionSeconds === '60' ? 'selected' : ''}>60 seconds</option>
                <option value="120" ${lobby.questionSeconds === '120' ? 'selected' : ''}>2 minutes</option>
                <option value="0" ${lobby.questionSeconds === '0' ? 'selected' : ''}>No time limit</option>
              </select>
            </label>
            <label>
              <span>Win condition</span>
              <select data-field="target">
                <option value="" ${lobby.target === '' ? 'selected' : ''}>Default for this mode</option>
                <option value="3" ${lobby.target === '3' ? 'selected' : ''}>First to 3</option>
                <option value="5" ${lobby.target === '5' ? 'selected' : ''}>First to 5</option>
                <option value="8" ${lobby.target === '8' ? 'selected' : ''}>First to 8</option>
                <option value="10" ${lobby.target === '10' ? 'selected' : ''}>First to 10</option>
                <option value="15" ${lobby.target === '15' ? 'selected' : ''}>First to 15</option>
              </select>
            </label>
          </div>

          ${importedTotal > 0
            ? `<div class="field-row">
                 <label>
                   <span>Question source</span>
                   <select data-field="source">
                     <option value="all" ${lobby.source !== 'imported' ? 'selected' : ''}>Built-in bank</option>
                     <option value="imported" ${lobby.source === 'imported' ? 'selected' : ''}>My imported questions (${importedTotal})</option>
                   </select>
                 </label>
               </div>`
            : `<p class="card-sub">Have your own question set? <button type="button" class="link-btn" data-action="navigate" data-route="import">Import it</button> and duel on exactly those questions.</p>`}

          <button type="button" class="focus-toggle ${lobby.focusMode ? 'is-on' : ''}" data-action="toggle-focus"
                  role="switch" aria-checked="${lobby.focusMode ? 'true' : 'false'}">
            <span class="focus-toggle-switch" aria-hidden="true"></span>
            <span class="focus-toggle-body">
              <strong>Focus Mode</strong>
              <span>Flags tab-switches and fullscreen exits to both players in real time during questions. This detects and reports lapses — it can't physically block a second device or a new tab, the way a browser never can.</span>
            </span>
          </button>

          <button class="btn btn-primary btn-block" data-action="create" ${offline ? 'disabled' : ''}>
            Create duel room →
          </button>
          <p class="status-line ${status.ok ? 'is-ok' : 'is-bad'}">
            <span class="status-dot" aria-hidden="true"></span>${status.html}
          </p>
        </section>

        <section class="card col-4">
          <h3 class="no-step">Already have a code?</h3>
          <p class="card-sub">Join a room a friend created.</p>
          <div class="vs-join">
            <input type="text" data-field="code" value="${esc(lobby.code)}" placeholder="ABCD"
                   maxlength="4" aria-label="Room code" class="code-field" />
            <button class="btn btn-ghost" data-action="join" ${offline ? 'disabled' : ''}>Join</button>
          </div>
          ${lobby.notice ? `<p class="vs-notice ${lobby.noticeBad ? 'is-bad' : ''}">${esc(lobby.notice)}</p>` : ''}

          <h3 class="spaced no-step">Your rivals</h3>
          ${rivals.length
            ? `<ul class="rival-list rival-list-compact">
                 ${rivals
                   .slice(0, 4)
                   .map(
                     (rival) => `
                     <li>
                       <span class="rival-name">${esc(rival.name)}</span>
                       <span class="rival-record ${rival.wins > rival.losses ? 'is-good' : rival.wins < rival.losses ? 'is-bad' : ''}">
                         ${rival.wins}–${rival.losses}${rival.draws ? `–${rival.draws}` : ''}
                       </span>
                     </li>`,
                   )
                   .join('')}
               </ul>`
            : '<p class="empty">No matches yet. Beat someone and they show up here.</p>'}
        </section>

        <section class="card col-12">
          <details class="vs-advanced">
            <summary>More ways to play</summary>
            <div class="advanced-body ${isSelfHosted() ? '' : 'advanced-body-solo'}">
              <div class="advanced-col">
                <h3 class="no-step">Challenge code</h3>
                <p class="card-sub">Not online at the same time? Play eight questions, send the code, and they race your run.</p>
                <button class="btn btn-ghost btn-block" data-action="challenge-send">Play a run to send</button>
                <div class="vs-join">
                  <input type="text" data-field="challenge" placeholder="Paste SQ1-… code" aria-label="Challenge code" />
                  <button class="btn btn-primary" data-action="challenge-accept">Accept</button>
                </div>
              </div>
              ${isSelfHosted() ? `
              <div class="advanced-col">
                <h3 class="no-step">Play someone not on your network</h3>
                <p class="card-sub">
                  Point this at a deployed match server. Leave empty to use whichever server sent you this page.
                  See <code>DEPLOY.md</code> for putting one online.
                </p>
                <div class="vs-join">
                  <input type="text" data-field="server" value="${esc(serverBase())}"
                         placeholder="https://your-server.example.com" aria-label="Match server URL" />
                  <button class="btn btn-ghost btn-sm" data-action="server">Use it</button>
                </div>
              </div>
              <div class="advanced-col">
                <h3 class="no-step">Fresh questions</h3>
                <p class="card-sub">
                  ${info?.generation
                    ? `Claude writes new original questions into the bank so neither of you memorizes it.`
                    : `Generation is off. Set <code>ANTHROPIC_API_KEY</code> in the shell running server.py, or run <code>python3 generate.py -n 20</code>.`}
                </p>
                <div class="gen-row">
                  <button class="btn btn-ghost" data-action="generate" data-count="5" ${info?.generation ? '' : 'disabled'}>Generate 5</button>
                  <button class="btn btn-ghost" data-action="generate" data-count="10" ${info?.generation ? '' : 'disabled'}>Generate 10</button>
                  <span class="gen-status">${esc(lobby.genStatus ?? '')}</span>
                </div>
              </div>` : ''}
            </div>
          </details>
        </section>
      </div>

      <footer class="foot">
        All questions are original items written for this app — not reproduced College Board material.
        Records and progress are stored in this browser.
      </footer>
    </div>`;

  root.oninput = (event) => {
    const field = event.target.closest('[data-field]');
    if (field) actions.setLobbyField(field.dataset.field, field.value);
  };

  root.onchange = (event) => {
    const radio = event.target.closest('input[name="mode"]');
    if (radio) actions.setLobbyField('mode', radio.value);
  };

  root.onclick = (event) => {
    const button = event.target.closest('[data-action]');
    if (!button) return;
    const { action } = button.dataset;
    if (action === 'navigate') actions.navigate(button.dataset.route);
    else if (action === 'create') actions.createMatch();
    else if (action === 'join') actions.joinMatch();
    else if (action === 'server') actions.setServer();
    else if (action === 'challenge-send') actions.sendChallenge();
    else if (action === 'challenge-accept') actions.acceptChallenge();
    else if (action === 'generate') actions.generate(Number(button.dataset.count));
    else if (action === 'theme') actions.cycleTheme();
    else if (action === 'toggle-focus') actions.setLobbyField('focusMode', !lobby.focusMode);
  };

  if (lobby.focusField) {
    const field = root.querySelector(`[data-field="${lobby.focusField}"]`);
    if (field) {
      field.focus();
      field.setSelectionRange?.(field.value.length, field.value.length);
    }
  }
  if (!lobby.name && !myName()) root.querySelector('[data-field="name"]')?.focus();
}
