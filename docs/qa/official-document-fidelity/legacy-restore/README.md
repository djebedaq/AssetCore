# Възстановяване само за бъдещи документи

Backend regression scenario: native Studio PART_REQUEST publication валидира двата варианта × 1/5/30. След explicit isolated activation се одобряват FREE_FORM KK1000 и machine KK1001; след confirmed legacy restore следва KK1002. Предходните GeneratedDocument bytes/hashes и RequestApprovalSnapshot hashes/template bytes се сравняват отново след промяна на company и machine данни.

Browser scenario изпълнява publish → explicit native activation → legacy restore само в нова disposable QA инсталация, проверява read-only configuration и append-only revisions. Публикуването само по себе си оставя legacy избора непроменен. Production избор не се извършва.
