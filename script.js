/* AI First — landing interactions */
(function () {
  "use strict";

  // Current year in footer
  var yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  var STORAGE_KEY = "aifirst_waitlist";

  function handleSignup(form, noteEl) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var input = form.querySelector('input[type="email"]');
      var btn = form.querySelector("button");
      var email = (input.value || "").trim();

      input.classList.remove("invalid");
      if (noteEl) noteEl.classList.remove("success", "error");

      if (!EMAIL_RE.test(email)) {
        input.classList.add("invalid");
        if (noteEl) {
          noteEl.textContent = "Please enter a valid email address.";
          noteEl.classList.add("error");
        }
        input.focus();
        return;
      }

      // Simulate a successful signup. Replace with a real API/Formspree/etc. call.
      var original = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Joining…";

      setTimeout(function () {
        try {
          var stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
          if (stored.indexOf(email) === -1) stored.push(email);
          localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
        } catch (err) {
          /* localStorage unavailable — ignore */
        }

        form.reset();
        btn.disabled = false;
        btn.textContent = "You're in! 🎉";
        if (noteEl) {
          noteEl.textContent = "Welcome aboard — check your inbox soon for early access.";
          noteEl.classList.add("success");
        }

        setTimeout(function () {
          btn.textContent = original;
        }, 2500);
      }, 700);
    });
  }

  var f1 = document.getElementById("signupForm");
  var f2 = document.getElementById("signupForm2");
  if (f1) handleSignup(f1, document.getElementById("signupNote"));
  if (f2) handleSignup(f2, document.getElementById("signupNote2"));

  // Subtle reveal on scroll
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.style.opacity = "1";
            entry.target.style.transform = "none";
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    var targets = document.querySelectorAll(".prop, .step, .track, .stat, .faq details");
    targets.forEach(function (el, i) {
      el.style.opacity = "0";
      el.style.transform = "translateY(16px)";
      el.style.transition = "opacity 0.5s ease " + (i % 3) * 0.06 + "s, transform 0.5s ease " + (i % 3) * 0.06 + "s";
      io.observe(el);
    });
  }
})();
