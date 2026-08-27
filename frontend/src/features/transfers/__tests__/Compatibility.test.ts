import { expect, it } from 'vitest'
import * as publicSurface from '../../../BulkTransfers'
import BulkTransfers from '../BulkTransfers'
import { BatchDetailsPanel, BatchProgressCard } from '../BatchHistory'
import { CancelBatchModal } from '../CancelBatchModal'
import { ConfirmationSummary, IssueResult } from '../TransferSummary'
import { ConflictNotice } from '../TransferConflictNotice'
import { IssueModal } from '../IssueFlow'
import { IssueSelectionList } from '../IssueSelectionList'
import { ReturnModal } from '../ReturnFlow'

it('preserves every original public export as the same feature implementation', () => {
  expect({ ...publicSurface }).toEqual({ default: BulkTransfers, BatchDetailsPanel, BatchProgressCard, CancelBatchModal, ConfirmationSummary, IssueResult, ConflictNotice, IssueModal, IssueSelectionList, ReturnModal })
})
