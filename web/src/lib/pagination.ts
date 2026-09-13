// Advance by the number actually returned: a server may cap pages below our request.
export async function readAllPages<T>(read: (from: number, to: number) => Promise<T[]>): Promise<T[]> {
  const rows: T[] = []
  for (;;) {
    const page = await read(rows.length, rows.length + 499)
    if (page.length === 0) return rows
    rows.push(...page)
  }
}
