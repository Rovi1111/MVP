from app.services.analytics import summarize
from app.services.markdown import render_markdown


def test_markdown_blocks():
    html = render_markdown(
        "# Общий тренд\nРасходы **выросли** на 5 %.\nВторая строка.\n\n"
        "**Рекомендации:**\n1. Первое\n2. Второе\n\n- пункт *важный*\n* пункт `код`"
    )
    assert "<h4>Общий тренд</h4>" in html and "<h4>Рекомендации:</h4>" in html
    assert "<p>Расходы <strong>выросли</strong> на 5 %.<br>Вторая строка.</p>" in html
    assert '<ol>\n<li value="1">Первое</li>\n<li value="2">Второе</li>\n</ol>' in html
    assert "<ul>\n<li>пункт <em>важный</em></li>\n<li>пункт <code>код</code></li>\n</ul>" in html


def test_markdown_keeps_numbers_when_list_is_interrupted():
    html = render_markdown("1. Раз\n\nПояснение.\n\n2. Два")
    assert '<li value="1">Раз</li>' in html and '<li value="2">Два</li>' in html


def test_markdown_escapes_html_from_model():
    html = render_markdown('<script>alert(1)</script> **<b>x</b>** <img src=x onerror="y">')
    assert "<script>" not in html and "<img" not in html and "<b>" not in html
    assert "&lt;script&gt;" in html and "<strong>&lt;b&gt;x&lt;/b&gt;</strong>" in html
    assert render_markdown(None) == "" and render_markdown("2 * 3 * 4") == "<p>2 * 3 * 4</p>"


def test_summarize():
    series = {"totals": [100.0, 140.0], "budget": [100.0, 100.0], "granularity": "month"}
    assert summarize(series) == {
        "fact": 240.0, "average": 120.0, "steps": 2, "granularity": "month",
        "budget": 200.0, "deviation": 40.0, "deviation_pct": 20.0, "execution_pct": 120.0,
    }  # fmt: skip
    no_budget = summarize({"totals": [5.0], "budget": None, "granularity": "day"})
    assert (
        no_budget["budget"] is None and no_budget["deviation"] is None and no_budget["fact"] == 5.0
    )
    zero_plan = summarize({"totals": [5.0], "budget": [0.0]})
    assert zero_plan["deviation"] == 5.0 and zero_plan["deviation_pct"] is None
    assert summarize({"totals": [], "budget": None})["average"] == 0.0
