document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".flash-message").forEach((message) => {
    window.setTimeout(() => {
      message.classList.add("flash-hide");
      window.setTimeout(() => message.remove(), 350);
    }, 6000);
  });
});
