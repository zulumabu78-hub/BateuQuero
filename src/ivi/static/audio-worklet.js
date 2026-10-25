class IVICapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(2048);
    this.offset = 0;
  }

  process(inputs, outputs) {
    const input = inputs[0]?.[0];
    const output = outputs[0]?.[0];
    if (output) output.fill(0);
    if (!input) return true;
    let cursor = 0;
    while (cursor < input.length) {
      const length = Math.min(input.length - cursor, this.buffer.length - this.offset);
      this.buffer.set(input.subarray(cursor, cursor + length), this.offset);
      this.offset += length;
      cursor += length;
      if (this.offset === this.buffer.length) {
        let energy = 0;
        for (const sample of this.buffer) energy += sample * sample;
        const samples = this.buffer;
        this.port.postMessage({ samples: samples.buffer, rms: Math.sqrt(energy / samples.length) }, [samples.buffer]);
        this.buffer = new Float32Array(2048);
        this.offset = 0;
      }
    }
    return true;
  }
}

registerProcessor('ivi-capture', IVICapture);
