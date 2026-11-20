/* Navbar avatar: swap to the initial circle if the Google photo fails. */
(function () {
  document.querySelectorAll('img.navbar-avatar').forEach(function (img) {
    img.addEventListener('error', function () {
      img.classList.add('d-none');
      var fallback = img.nextElementSibling;
      if (fallback && fallback.classList.contains('navbar-avatar-fallback')) {
        fallback.classList.remove('d-none');
      }
    });
  });
})();
