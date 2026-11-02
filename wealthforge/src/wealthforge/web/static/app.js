// Small progressive enhancements. Every form works without JavaScript.
document.addEventListener("submit", (event) => {
  const form = event.target;
  const question = form.dataset.confirm;
  if (question && !window.confirm(question)) {
    event.preventDefault();
    return;
  }
  const busy = form.dataset.busy;
  if (busy) {
    const button = form.querySelector("button");
    if (button) {
      button.disabled = true;
      button.textContent = busy;
    }
  }
});
