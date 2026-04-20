export class LatestAsyncValueRunner<T> {
  private running: Promise<void> | null = null
  private pendingValue: T | null = null
  private closed = false
  private readonly worker: (value: T) => Promise<void>

  constructor(worker: (value: T) => Promise<void>) {
    this.worker = worker
  }

  push(value: T): Promise<void> {
    this.pendingValue = value
    if (this.running) {
      return this.running
    }

    const loop = this.drain().finally(() => {
      if (this.running === loop) {
        this.running = null
      }
      if (this.pendingValue !== null && !this.closed) {
        void this.push(this.pendingValue)
      }
    })
    this.running = loop
    return loop
  }

  clear(): void {
    this.pendingValue = null
  }

  close(): void {
    this.closed = true
    this.clear()
  }

  private async drain(): Promise<void> {
    while (this.pendingValue !== null) {
      const nextValue = this.pendingValue
      this.pendingValue = null
      await this.worker(nextValue)
    }
  }
}
