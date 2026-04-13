export const runInThisContext = <T = unknown>(code: string): T =>
  Function(`"use strict"; return (${code});`)() as T

const vm = {
  runInThisContext,
}

export default vm
