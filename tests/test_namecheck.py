from collector.namecheck import lengths, name_fields, report

XML = """<Root><Items>
<Item><ItemCode>1</ItemCode><ItemName>{a}</ItemName><ItemPrice>5</ItemPrice>
<ManufacturerItemDescription>{b}</ManufacturerItemDescription></Item>
<Item><ItemCode>2</ItemCode><ItemName>קצר</ItemName><ItemPrice>6</ItemPrice></Item>
</Items></Root>"""


def test_reads_the_raw_name_fields_without_changing_them():
    text = XML.format(a="א" * 20, b="א" * 20 + " ארוך יותר")
    rows = name_fields(text)
    assert rows[0] == {"itemname": "א" * 20, "manufactureritemdescription": "א" * 20 + " ארוך יותר"}
    assert rows[1] == {"itemname": "קצר", "manufactureritemdescription": ""}


def test_the_report_shows_how_many_names_have_the_longest_length():
    out = report("demo", XML.format(a="א" * 20, b="ב" * 40))
    assert "longest ItemName 20, with that length: 1" in out
    assert "present on 1 items" in out and (40, 1) in lengths(["ב" * 40])
