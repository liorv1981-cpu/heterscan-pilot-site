import { expect, it } from 'vitest'
import { readAllPages } from './pagination'

it('loads beyond the API default cap and handles smaller server pages without losing rows', async () => {
  const source = Array.from({ length: 1253 }, (_, id) => id)
  const values = await readAllPages(async (from, to) => source.slice(from, Math.min(to + 1, from + 200)))
  expect(values).toEqual(source)
})

it('propagates a later-page failure instead of silently presenting partial results', async () => {
  await expect(readAllPages(async (from) => {
    if (from) throw new Error('offline')
    return [1, 2]
  })).rejects.toThrow('offline')
})
