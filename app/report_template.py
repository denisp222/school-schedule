"""Generic documents built from scratch; no private template or metadata."""
from io import BytesIO


def generic_template(state, audience):
    from docx import Document
    from docx.shared import Cm, Pt
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(29.7), Cm(21)
    section.top_margin = section.bottom_margin = Cm(1)
    section.left_margin = section.right_margin = Cm(1)
    style = document.styles['Normal']
    style.font.name, style.font.size = 'Arial', Pt(9)
    style.paragraph_format.space_after = Pt(0)
    document.core_properties.author = ''
    document.core_properties.last_modified_by = ''
    document.add_paragraph('ПОНЕДЕЛЬНИК')
    if audience == 'teachers':
        table = document.add_table(rows=1, cols=9)
        for cell, text in zip(table.rows[0].cells, ['ПОНЕДЕЛЬНИК', *map(str, range(1, 9))]):
            cell.text = text
        for teacher in state['teachers']:
            table.add_row().cells[0].text = teacher['name']
        if not state['teachers']:table.add_row()
        table.add_row().cells[0].text = 'Свободные кабинеты'
    else:
        # Small blocks are readable even if there are many classes.
        table = document.add_table(rows=0, cols=5)
        classes = state['classes']
        for offset in range(0, max(len(classes), 1), 4):
            block = classes[offset:offset+4]
            cells = table.add_row().cells
            cells[0].text = '№'
            for cell, cls in zip(cells[1:], block):
                cell.text = cls['name']
            for period in range(1, 9):
                table.add_row().cells[0].text = str(period)
    table.style = 'Table Grid'
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()
