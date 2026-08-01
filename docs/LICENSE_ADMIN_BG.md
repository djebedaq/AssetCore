# Администриране на лиценза

Лицензът е offline JSON envelope с `payload` и отделен Base64 Ed25519
`signature`. Частният ключ се държи единствено от правообладателя и никога не се
копира в repository, клиентския сървър или browser bundle. AssetCore съдържа само
публичния ключ за проверка.

Управление има само активен administrator със завършен профил, който е текущият
installation owner. Екранът „Лиценз на AssetCore“ показва правообладател, клиент,
ID, тип, статус, модули, срок, поддръжка, installation ID и последна проверка.
Инсталирането проверява signature, canonical payload hash, правообладател,
installation, среда, домейн, тип, срокове, брой инсталации и лимити. Отказът и
успехът се одитират; предишният лиценз се пази като superseded.

Поддържаните типове са `TEST`, `TRIAL`, `ANNUAL`, `PERPETUAL`, `SUPPORT_ONLY` и
`EMERGENCY_TEMPORARY`. При изтичане се прилага подписаният grace period. След
него системата е read-only: няма изтриване, export и backup остават достъпни, а
owner може да инсталира нов валиден или временен авариен лиценз.

Не редактирайте лицензния файл. Всяка промяна обезсилва подписа. За прехвърляне
на installation owner използвайте защитената форма с текуща парола, основание и
друг активен administrator със завършен профил. Owner не е роля и не присъства в
role dropdown.

API: `GET /api/license/status`, `GET /api/license/validate`,
`POST /api/license/install`, `GET /api/owner`, `GET /api/owner/audit` и
`POST /api/owner/transfer`.
