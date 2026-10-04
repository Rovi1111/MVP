// Небольшие улучшения интерфейса без фреймворков.
document.addEventListener("DOMContentLoaded", () => {
  // Drag&drop: файл попадает в скрытый input, форма отправляется через HTMX
  document.querySelectorAll(".dropzone").forEach((zone) => {
    const input = zone.querySelector("input[type=file]");
    const form = zone.closest("form");
    const send = () => { if (input.files.length) htmx.trigger(form, "submit"); };
    ["dragenter", "dragover"].forEach((name) =>
      zone.addEventListener(name, (e) => { e.preventDefault(); zone.classList.add("over"); }));
    ["dragleave", "drop"].forEach((name) =>
      zone.addEventListener(name, (e) => { e.preventDefault(); zone.classList.remove("over"); }));
    zone.addEventListener("drop", (e) => {
      if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; send(); }
    });
    input.addEventListener("change", send);
    // сброс, чтобы тот же файл можно было загрузить повторно
    form.addEventListener("htmx:afterRequest", () => form.reset());
  });

  // Вкладки
  document.querySelectorAll("[data-tabs]").forEach((tabs) => {
    const buttons = tabs.querySelectorAll("[data-tab]");
    buttons.forEach((button) => button.addEventListener("click", () => {
      buttons.forEach((b) => {
        b.classList.toggle("active", b === button);
        document.getElementById(b.dataset.tab).hidden = b !== button;
      });
    }));
  });
});

// Строки формы ручного ввода и кнопка «Скопировать» (делегирование: работает и после HTMX-обновлений)
document.addEventListener("click", (e) => {
  if (!(e.target instanceof Element)) return;
  const add = e.target.closest("[data-add-row]");
  if (add) {
    const body = document.querySelector(add.dataset.addRow + " tbody");
    const row = body.rows[body.rows.length - 1].cloneNode(true);
    row.querySelectorAll("input").forEach((input) => { input.value = ""; });
    body.appendChild(row);
  }
  const remove = e.target.closest("[data-remove-row]");
  if (remove) {
    const row = remove.closest("tr");
    if (row.parentElement.rows.length > 1) row.remove();
    else row.querySelectorAll("input").forEach((input) => { input.value = ""; });
  }
  const copy = e.target.closest("[data-copy]");
  if (copy) {
    navigator.clipboard.writeText(document.querySelector(copy.dataset.copy).innerText).then(() => {
      const label = copy.textContent;
      copy.textContent = "Скопировано";
      setTimeout(() => { copy.textContent = label; }, 1500);
    });
  }
});

// Быстрые периоды: кнопка подставляет даты и обновляет диаграмму
document.addEventListener("click", (e) => {
  if (!(e.target instanceof Element)) return;
  const preset = e.target.closest("[data-preset]");
  if (!preset) return;
  const form = preset.closest("form");
  form.elements.date_from.value = preset.dataset.from;
  form.elements.date_to.value = preset.dataset.to;
  markPreset(form);
  htmx.trigger(form, "submit");
});
// Подсветка кнопки, совпадающей с выбранными датами
function markPreset(form) {
  form.querySelectorAll("[data-preset]").forEach((button) => {
    button.classList.toggle("active",
      button.dataset.from === form.elements.date_from.value &&
      button.dataset.to === form.elements.date_to.value);
  });
}
document.addEventListener("change", (e) => {
  if (e.target instanceof HTMLInputElement && e.target.type === "date" && e.target.form) {
    markPreset(e.target.form);
  }
});

// ---------- Тема оформления ----------
function currentTheme() { return document.documentElement.dataset.theme === "light" ? "light" : "dark"; }
function labelThemeButtons() {
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.textContent = currentTheme() === "dark" ? "☀ Светлая" : "☾ Тёмная";
    button.title = "Переключить тему оформления";
  });
}
document.addEventListener("DOMContentLoaded", labelThemeButtons);
document.addEventListener("click", (e) => {
  if (!(e.target instanceof Element) || !e.target.closest("[data-theme-toggle]")) return;
  const theme = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("theme", theme);
  labelThemeButtons();
  document.querySelectorAll(".chart").forEach(drawChart);  // перекрасить диаграммы
});

// ---------- Диаграммы Plotly ----------
// Сервер отдаёт фигуру в светлом оформлении (оно же идёт в PNG и PDF);
// на странице цвета подстраиваются под выбранную тему.
function themedFigure(figure) {
  const dark = currentTheme() === "dark";
  const text = dark ? "#e6eaf2" : "#18202e";
  const grid = dark ? "#2a3445" : "#e6e9ee";
  const layout = structuredClone(figure.layout);
  Object.assign(layout, { paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)" });
  layout.font = { ...layout.font, color: text };
  layout.xaxis = { ...layout.xaxis, linecolor: grid, tickcolor: grid };
  layout.yaxis = { ...layout.yaxis, gridcolor: grid, zerolinecolor: grid };
  layout.hoverlabel = { bgcolor: dark ? "#1d2532" : "#ffffff", bordercolor: grid, font: { color: text } };
  const data = figure.data.map((trace) => trace.type === "scatter"
    ? { ...trace, line: { ...trace.line, color: dark ? "#f4f6fb" : "#1c2330" } }  // линия бюджета
    : { ...trace, marker: { ...trace.marker, line: { width: 0 } } });
  return { data, layout };
}
function drawChart(el) {
  if (!window.Plotly || !el._figure) return;
  const { data, layout } = themedFigure(el._figure);
  Plotly.react(el, data, layout, { responsive: true, displaylogo: false, locale: "ru" });
}
function renderCharts(root) {
  root.querySelectorAll(".chart[data-figure]").forEach((el) => {
    el._figure = JSON.parse(el.dataset.figure);
    el.removeAttribute("data-figure");
    drawChart(el);
  });
}
document.addEventListener("DOMContentLoaded", () => renderCharts(document));
document.addEventListener("htmx:afterSettle", (e) => renderCharts(e.target));
