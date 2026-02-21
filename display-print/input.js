const inputEl = document.getElementById('textInput');
let isComposing = false;

inputEl.addEventListener('compositionstart', () => {
  isComposing = true;
});

inputEl.addEventListener('compositionend', () => {
  isComposing = false;
});

inputEl.addEventListener('keydown', async (e) => {
  if (e.key !== 'Enter') return;
  if (isComposing || e.isComposing) return;
  e.preventDefault();

  const value = inputEl.value.trim();
  if (!value) return;

  try {
    const response = await fetch('/api/inputs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value })
    });

    if (!response.ok) {
      console.error('Failed to save input:', await response.text());
      return;
    }

    inputEl.value = '';
  } catch (error) {
    console.error('Failed to save input:', error);
  }
});
