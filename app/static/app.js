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

// Форма анализа: поля периода зависят от детализации
function applyMode(select) {
  const form = select.closest("form");
  form.querySelectorAll("[data-mode]").forEach((el) => {
    el.hidden = !el.dataset.mode.split(" ").includes(select.value);
  });
}
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-mode-select]").forEach((select) => {
    applyMode(select);
    select.addEventListener("change", () => applyMode(select));
  });
});

// Диаграммы Plotly: рисуем после загрузки страницы и после каждого обновления HTMX
function renderCharts(root) {
  if (!window.Plotly) return;
  root.querySelectorAll(".chart[data-figure]").forEach((el) => {
    const figure = JSON.parse(el.dataset.figure);
    Plotly.newPlot(el, figure.data, figure.layout, { responsive: true, displaylogo: false, locale: "ru" });
    el.removeAttribute("data-figure");
  });
}
document.addEventListener("DOMContentLoaded", () => renderCharts(document));
document.addEventListener("htmx:afterSettle", (e) => renderCharts(e.target));

// Сортировка по клику на заголовок таблицы сравнения
document.addEventListener("click", (e) => {
  const th = e.target.closest("th[data-sort]");
  const form = document.getElementById("analysis-form");
  if (!th || !form || !form.elements.sort) return;
  const same = form.elements.sort.value === th.dataset.sort;
  form.elements.order.value = same && form.elements.order.value === "desc" ? "asc" : "desc";
  form.elements.sort.value = th.dataset.sort;
  htmx.trigger(form, "submit");
});
