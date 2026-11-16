"""Four-week individual teaching cards. No home addresses or extra personal data."""
from datetime import timedelta
from io import BytesIO
from docx import Document
from docx.shared import Cm, Pt
from .commitments import matching
from .rotation import number


def export(state, monday, learner_id=''):
    learners=[r for r in state.get('individualLearners',[]) if not learner_id or r['id']==learner_id]
    if not learners:raise ValueError('Сначала добавьте индивидуального ученика.')
    document=Document();section=document.sections[0]
    section.top_margin=section.bottom_margin=Cm(1.3)
    section.left_margin=section.right_margin=Cm(1.3)
    style=document.styles['Normal'];style.font.name='Calibri';style.font.size=Pt(9)
    classes={r['id']:r['name'] for r in state['classes']}
    teachers={r['id']:r['name'] for r in state['teachers']}
    subjects={r['id']:r['name'] for r in state['subjects']}
    rooms={r['id']:r['name'] for r in state['rooms']}
    current=number(state,monday)
    weeks={w:monday+timedelta(weeks=(w-current)%4) for w in range(1,5)}
    for i,learner in enumerate(learners):
        if i:document.add_page_break()
        document.add_heading('Индивидуальное расписание',0)
        document.add_paragraph(learner['name']+' · '+classes[learner['classId']])
        table=document.add_table(rows=1,cols=6);table.style='Table Grid'
        for cell,text in zip(table.rows[0].cells,['День','Урок',*[f'{w}-я неделя' for w in range(1,5)]]):cell.text=text
        for d,title in enumerate(['Пн','Вт','Ср','Чт','Пт']):
            entries={w:matching(state,weeks[w]+timedelta(days=d),include_cancelled=True) for w in weeks}
            active=sorted({r['first'] for rows in entries.values() for r in rows if r.get('learnerId')==learner['id']})
            for p in active:
                cells=table.add_row().cells;cells[0].text=title;cells[1].text=str(p)
                for w in weeks:
                    rows=[r for r in entries[w] if r.get('learnerId')==learner['id'] and r['first']==p]
                    cells[w+1].text='\n'.join(('Отменено: ' if r.get('cancelled') else '')+subjects.get(r.get('subjectId'),r['label'])+'\n'+teachers[r['teacherId']]+(' · каб. '+rooms[r['roomId']] if r.get('roomId') else '') for r in rows) or '—'
        document.add_paragraph('Недели повторяются в порядке 1 → 2 → 3 → 4 → 1. Разрывы дня и восьмой урок действуют только для указанных индивидуальных занятий.')
    stream=BytesIO();document.save(stream);return stream.getvalue()
