from pathlib import Path
from zipfile import ZipFile
from lxml import etree as E
import hashlib, json

root=Path(__file__).resolve().parent
ref=Path(r'C:\Users\Admin\Downloads\Концепция.docx')
out=root.parents[1]/'output'/'Концепция OCR Pipeline Creator.docx'
out.parent.mkdir(exist_ok=True)
ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W='{'+ns['w']+'}'
texts=[
'Концепция конструктора OCR Pipeline Creator',
'Настраиваемая обработка документов и извлечение данных с помощью языковых моделей',
'Назначение системы',
'Система предназначена для распознавания документов и преобразования их содержимого в текст или набор заданных полей. Пользователь настраивает сценарий обработки в визуальном конструкторе, сохраняет его как пайплайн и применяет к новым файлам. Результаты доступны в общей истории рабочего пространства и через API для внешних систем.',
'Основной принцип',
'В системе разделяются получение текста и его дальнейшая обработка. Текст извлекается из цифрового документа либо распознается по скану. Затем языковая модель выполняет инструкцию или заполняет заданные поля. Каждый этап настраивается отдельно; если обработка моделью отключена, результатом остается полученный текст.',
'Структура пайплайна',
'Пайплайн объединяет настройки для повторяемой обработки документов:',
'Сохраненный сценарий обработки',
'Уникальный идентификатор и название',
'Тип источника — цифровой документ или скан',
'Способ OCR — vision-модель или внешний сервис',
'Модель извлечения и параметры генерации',
'Инструкция для обработки текста',
'Имена и описания извлекаемых полей',
'Переключатели OCR, инструкции и извлечения полей',
'Конструктор состоит из трех этапов: название, источник и обработка. Инструкция и поля включаются независимо; при совместном включении инструкция уточняет правила извлечения. Пайплайн хранится в PostgreSQL, имеет постоянный ID и используется как в интерфейсе, так и при запуске через API.',
'Подготовка и настройка обработки',
'1. Администратор задает название и уникальный ID пайплайна, по которому внешние системы смогут запускать обработку.',
'2. Выбирается тип источника. PDF с текстовым слоем, DOCX и текстовые файлы читаются напрямую; для сканов и изображений настраивается OCR.',
'3. Для распознавания указывается vision-модель через LiteLLM либо адрес OCR-сервиса с необходимыми параметрами.',
'4. Для дальнейшей обработки выбирается модель, задается инструкция и при необходимости список полей с описаниями.',
'5. Настройки сохраняются. Качество сценария следует проверять на характерных документах перед подключением к рабочему процессу.',
'Обработка пользовательского документа',
'1. Пользователь выбирает сохраненный пайплайн и загружает файл. Внешняя система передает файл и ID пайплайна через API.',
'2. При фоновом запуске исходник сохраняется в S3, а задача и событие ее отправки — в PostgreSQL. Диспетчер передает задачу в очередь Redis.',
'3. Воркер получает файл и извлекает текст напрямую либо выполняет OCR. При включенной обработке текст передается выбранной модели.',
'4. Для режима полей проверяются формат JSON, состав ключей и типы значений. Некорректный ответ завершает задачу с ошибкой.',
'5. Успешный результат сохраняется в истории. Пользователь просматривает исходник, текст и поля; интеграция получает результат через API.',
'Режимы обработки и интеграция',
'Интерфейс запускает обработку в фоне с отображением состояния задачи. API поддерживает синхронный ответ и фоновый запуск с идентификатором для проверки статуса. Для каждой интеграции создается отдельный API-ключ с доступом к выбранным пайплайнам. Ключ позволяет получать только собственные задачи и документы.',
'Хранение и проверка результатов',
'Исходные файлы хранятся в приватном S3-хранилище, а настройки, задачи, распознанный текст и результаты — в PostgreSQL. В истории можно открыть или скачать исходник и исправить извлеченные поля. Правки не изменяют исходный файл и первоначальный ответ модели. Контроль ревизии предотвращает перезапись конфликтующих изменений.',
'Исходник — загруженный документ для последующей проверки',
'Текст — содержимое после чтения файла или OCR',
'Результат — исходный ответ модели в виде текста или JSON',
'Поля — текущие значения с учетом правок пользователя',
'Задача — состояние обработки, число попыток и сведения об ошибке',
'Правила надежности',
'Сохранение исходника. Результат можно сверить с загруженным документом.',
'Строгая схема. В режиме полей допускаются только заданные ключи и значения в виде строк или null.',
'Явная ошибка. Отказ модели или неверный JSON не сохраняется как успешный документ.',
'Контроль повторов. Временные сбои обрабатываются повторными попытками в пределах лимитов.',
'Защита результата. Устаревшие запуски задачи не могут перезаписать итог обработки.',
'Разграничение доступа. Администратор управляет настройками, пользователь работает с документами, API-ключ ограничен своей интеграцией.',
'Оценка качества',
'Ожидаемый результат',
'Проект объединяет распознавание, извлечение данных и проверку результатов в настраиваемый процесс. Ожидаемый эффект — сокращение ручного переноса сведений и времени подключения новых типов документов. Пайплайны позволяют повторно использовать настройки, а API — включать обработку в другие системы. Качество зависит от исходных файлов и выбранных моделей; его следует оценивать на эталонной выборке с проверкой результатов человеком.'
]
tables=[
[['Этап','Содержимое','Назначение'],['Получение текста','Чтение цифрового файла или OCR скана','Подготовка текста для дальнейшей обработки'],['Обработка текста','Инструкция, модель и схема извлекаемых полей','Свободный текст или структурированный JSON']],
[['Метрика','Что измеряет'],['Точность распознавания','Доля ошибок в символах и словах относительно эталонного текста'],['Точность значений полей','Доля полей, значения которых совпадают с эталоном'],['Полнота извлечения','Доля присутствующих в документе целевых значений, которые удалось извлечь'],['Соответствие схеме','Доля ответов модели, прошедших проверку JSON и типов значений'],['Время обработки','Полное время от приема файла до результата, включая ожидание в очереди'],['Доля ручных исправлений','Доля извлеченных полей, исправленных пользователем после обработки']]
]
with ZipFile(ref) as z:
 parts={i.filename:z.read(i) for i in z.infolist()}
 doc=E.fromstring(parts['word/document.xml'])
 body=doc.find('w:body',ns)
 ps=body.findall('w:p',ns)
 assert len(ps)==len(texts)
 def replace(p,text):
  nodes=p.findall('.//w:t',ns)
  if not nodes: raise ValueError('No text slot')
  nodes[0].text=text
  for t in nodes[1:]: t.text=''
 for p,text in zip(ps,texts): replace(p,text)
 for t,rows in zip(body.findall('w:tbl',ns),tables):
  for tr,values in zip(t.findall('w:tr',ns),rows):
   for tc,value in zip(tr.findall('w:tc',ns),values):
    replace(tc,value)
 parts['word/document.xml']=E.tostring(doc,xml_declaration=True,encoding='UTF-8',standalone=True)
 with ZipFile(out,'w') as dest:
  for info in z.infolist(): dest.writestr(info,parts[info.filename])
 inventory={k:hashlib.sha256(v).hexdigest() for k,v in parts.items()}
 (root/'package-inventory.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
 styles=E.fromstring(parts['word/styles.xml'])
 (root/'style-evidence.xml').write_bytes(E.tostring(styles,pretty_print=True))
 (root/'section-evidence.xml').write_bytes(E.tostring(body.find('w:sectPr',ns),pretty_print=True))
 (root/'artifact.md').write_text('''# Template contract
Reference: C:/Users/Admin/Downloads/Концепция.docx
SHA256: '''+hashlib.sha256(ref.read_bytes()).hexdigest()+'''
Reference rendered with Microsoft Word to reference.pdf and ref-1.png through ref-3.png after packaged renderer failed because bundled LibreOffice is unavailable on Windows.
Three reference pages, one portrait section, Letter 21.59 x 27.94 cm. Margins top/bottom 1.82915 cm, left/right 2.08315 cm.
All original style definitions, direct paragraph and run formatting, numbering, tables and page breaks are preserved. Exact style and section evidence is in style-evidence.xml and section-evidence.xml.
Visual system: black bold title, gray subtitle, black bold section headings, compact body paragraphs, nested bullet list, two blue-header tables with alternating light rows. No added decoration.
Editable slots: word/document.xml/body direct paragraphs 0–47; text nodes of both tables. All slots rewritten for OCR project, with the same logical section order and comparable length. Original three-page flow and explicit breaks preserved.
All package parts except word/document.xml are preserve-only, including styles, numbering, relationships and metadata. All non-text nodes within document.xml are preserve-only.
Fidelity gates: compare package bytes, section geometry, paragraph styles, row counts, source hash, and inspect each final rendered page.
''',encoding='utf-8')
with ZipFile(ref) as a, ZipFile(out) as b:
 assert a.namelist()==b.namelist()
 assert all(a.read(n)==b.read(n) for n in a.namelist() if n!='word/document.xml')
print(out)
