export const PASSWORD_MIN_LENGTH = 8

const PASSWORD_POLICY_TEXT = {
  bg: 'Минимум 8 знака и поне една цифра; паролата не трябва да е очевидно слаба или идентична със служебния имейл.',
  en: 'At least 8 characters and at least one digit; the password must not be obviously weak or identical to the business email.',
  ru: 'Минимум 8 символов и хотя бы одна цифра; пароль не должен быть очевидно слабым или совпадать с рабочим email.',
} as const

export function passwordPolicyText(language?: string): string {
  if (language === 'en' || language === 'ru') return PASSWORD_POLICY_TEXT[language]
  return PASSWORD_POLICY_TEXT.bg
}
