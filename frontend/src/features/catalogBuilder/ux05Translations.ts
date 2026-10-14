export const ux05Bg = {
  'ux05.optionalReview': 'Допълнителната проверка спрямо оригинала е по избор. Еднократното потвърждение на частите е достатъчно за публикация. Нерешените конфликти трябва да бъдат отстранени.',
  'ux05.sourceParts': 'PDF списъкът няма потвърдени и свързани части. Потвърдете приложимите редове или поправете избора на страница.',
  'ux05.conflict': 'Има нерешено противоречие между разпознати кандидати. Разрешете го в Части.',
  'ux05.mapping': 'Потвърден кандидат сочи към липсваща, чужда или неправилно свързана част. Поправете връзката в Части.',
  'ux05.running': 'Извличането още работи. Изчакайте резултата преди публикация.',
  'ux05.integrity': 'Запазеното доказателство от извличането е повредено. Възстановете валиден източник преди публикация.',
  'ux05.inspect': 'Прегледай',
} as const
export const ux05En: Record<keyof typeof ux05Bg, string> = {
  'ux05.optionalReview': 'Additional review against the original is optional. Confirming parts once is sufficient for publication. Unresolved conflicts must be corrected.',
  'ux05.sourceParts': 'This PDF list has no confirmed, linked parts. Confirm the applicable rows or correct the page selection.',
  'ux05.conflict': 'Extracted candidates have an unresolved conflict. Resolve it in Parts.',
  'ux05.mapping': 'A confirmed candidate points to a missing, foreign or incorrectly linked part. Correct the link in Parts.',
  'ux05.running': 'Extraction is still running. Wait for the result before publishing.',
  'ux05.integrity': 'Stored extraction evidence is corrupted. Restore a valid source before publishing.',
  'ux05.inspect': 'Review',
}
export const ux05Ru: Record<keyof typeof ux05Bg, string> = {
  'ux05.optionalReview': 'Дополнительная проверка по оригиналу необязательна. Одного подтверждения деталей достаточно для публикации. Неразрешённые конфликты необходимо устранить.',
  'ux05.sourceParts': 'У этого PDF списка нет подтверждённых связанных деталей. Подтвердите нужные строки или исправьте выбор страницы.',
  'ux05.conflict': 'У распознанных кандидатов есть неразрешённое противоречие. Разрешите его в Деталях.',
  'ux05.mapping': 'Подтверждённый кандидат ссылается на отсутствующую, чужую или неверно связанную деталь. Исправьте связь в Деталях.',
  'ux05.running': 'Извлечение ещё работает. Дождитесь результата перед публикацией.',
  'ux05.integrity': 'Сохранённое доказательство извлечения повреждено. Восстановите действительный источник перед публикацией.',
  'ux05.inspect': 'Просмотреть',
}
