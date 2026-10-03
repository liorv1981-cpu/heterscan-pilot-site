export type CollectionMode = 'full_details' | 'public_summary'

export function collectionModeFor(adapterName: string, requested: unknown): CollectionMode {
  const mode = requested === undefined ? 'full_details' : requested
  if (mode !== 'full_details' && mode !== 'public_summary') {
    throw new Error('היקף הסריקה אינו תקין.')
  }
  if (mode === 'public_summary' && adapterName !== 'complot') {
    throw new Error('סיכומי בקשות בלבד אינם נתמכים במקור של העיר שנבחרה.')
  }
  return mode
}
