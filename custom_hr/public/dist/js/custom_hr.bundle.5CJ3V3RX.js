(() => {
  // ../custom_hr/custom_hr/public/js/custom_hr.bundle.js
  for (const page of ["employee-attendance-gallery", "outlet-roster"]) {
    try {
      localStorage.removeItem(`_page:${page}`);
    } catch (e) {
    }
  }
})();
//# sourceMappingURL=custom_hr.bundle.5CJ3V3RX.js.map
