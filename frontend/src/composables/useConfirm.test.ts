import { describe, it, expect } from 'vitest'
import { useConfirm } from './useConfirm'

describe('useConfirm', () => {
  it('resolves true when settled with confirm', async () => {
    const { confirm, current, settle } = useConfirm()
    const p = confirm({ title: 'T', message: 'M' })
    expect(current.value?.title).toBe('T')
    settle(true)
    await expect(p).resolves.toBe(true)
    expect(current.value).toBeNull()
  })

  it('resolves false when settled with cancel', async () => {
    const { confirm, settle } = useConfirm()
    const p = confirm({ title: 'T', message: 'M' })
    settle(false)
    await expect(p).resolves.toBe(false)
  })

  it('a new request cancels a stale unresolved one', async () => {
    const { confirm } = useConfirm()
    const stale = confirm({ title: 'A', message: 'M' })
    const fresh = confirm({ title: 'B', message: 'M' })
    await expect(stale).resolves.toBe(false)
    const { settle } = useConfirm()
    settle(true)
    await expect(fresh).resolves.toBe(true)
  })
})
