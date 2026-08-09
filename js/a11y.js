// Screen-reader announcements.
//
// The match screen changes constantly without focus ever moving — a round
// resolves, the score ticks, a steal window opens. Sighted players see it; this
// is how everyone else is told. Kept in its own module so both the router and
// the views can announce without importing each other.

let lastMessage = '';

export function announce(message) {
  const region = document.getElementById('announcer');
  if (!region || !message || message === lastMessage) return;
  lastMessage = message;
  // Assigning identical text does not re-announce, so clear first.
  region.textContent = '';
  window.setTimeout(() => {
    region.textContent = message;
  }, 60);
}

/** Let the next identical message through (e.g. a new round of the same shape). */
export function resetAnnouncer() {
  lastMessage = '';
}
