import { randomUUID } from 'node:crypto';
import type { Writable } from 'node:stream';
import { safeFailure } from './errors.js';

/** Serialize writes so a slow reader cannot reorder or lose an event. */
export class EventStream {
  runId: string = randomUUID();
  labels: Record<string, string> | undefined;
  textOnly = false;
  private sequence = 0;
  private finished = false;
  private writes: Promise<void> = Promise.resolve();
  constructor(readonly output: Writable = process.stdout) {}
  emit(type: string, data: Record<string, unknown> = {}): void {
    if (this.finished) return;
    const record = { runId: this.runId, seq: ++this.sequence, at: new Date().toISOString(),
      ...(this.labels === undefined ? {} : { labels: this.labels }), type, ...data };
    if (type === 'finished') this.finished = true;
    const text = this.textOnly ? type === 'text' && data.parentCallId === undefined ? String(data.text) : '' : JSON.stringify(record) + '\n';
    if (text) this.writes = this.writes.then(() => new Promise<void>((resolve, reject) =>
      this.output.write(text, error => error ? reject(error) : resolve())));
    // The runner observes errors through flush; attach a handler immediately.
    void this.writes.catch(() => {});
  }
  flush(): Promise<void> { return this.writes; }
  async finish(error?: unknown, cancelled = false, data: Record<string, unknown> = {}): Promise<number> {
    const status = cancelled ? 2 : error === undefined ? 0 : 1;
    this.emit('finished', { outcome: cancelled ? 'cancelled' : error === undefined ? 'completed' : 'failed',
      ...(error === undefined || cancelled ? {} : { error: safeFailure(error) }), producedOutput: false, unfinishedCalls: [], ...data });
    await this.flush();
    return status;
  }
}
