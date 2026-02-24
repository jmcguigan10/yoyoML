"use strict";

const state = {
  inputSize: 4,
  outputSize: 1,
  learningRate: 0.01,
  taskType: "regression",
  hiddenLayers: [
    { id: 1, units: 8, activation: "relu" },
    { id: 2, units: 4, activation: "relu" }
  ],
  nextLayerId: 3,
  model: null
};

const els = {
  inputSize: document.getElementById("inputSize"),
  outputSize: document.getElementById("outputSize"),
  learningRate: document.getElementById("learningRate"),
  taskType: document.getElementById("taskType"),
  addLayerBtn: document.getElementById("addLayerBtn"),
  resetBtn: document.getElementById("resetBtn"),
  buildBtn: document.getElementById("buildBtn"),
  layerList: document.getElementById("layerList"),
  layerRowTemplate: document.getElementById("layerRowTemplate"),
  builderStatus: document.getElementById("builderStatus"),
  paramCount: document.getElementById("paramCount"),
  layerCount: document.getElementById("layerCount"),
  outputActivation: document.getElementById("outputActivation"),
  networkCanvas: document.getElementById("networkCanvas"),
  inputVector: document.getElementById("inputVector"),
  inferBtn: document.getElementById("inferBtn"),
  randomInputBtn: document.getElementById("randomInputBtn"),
  inferenceOutput: document.getElementById("inferenceOutput"),
  modelJson: document.getElementById("modelJson"),
  copyBtn: document.getElementById("copyBtn")
};

class SimpleDenseNetwork {
  constructor(layerSpecs) {
    this.layerSpecs = layerSpecs;
    this.weights = [];
    this.biases = [];

    for (const spec of layerSpecs) {
      const scale = Math.sqrt(2 / Math.max(spec.in, 1));
      this.weights.push(randomMatrix(spec.out, spec.in, scale));
      this.biases.push(randomVector(spec.out, 0.08));
    }
  }

  forward(inputVector) {
    let activations = inputVector.slice();

    for (let i = 0; i < this.layerSpecs.length; i += 1) {
      const weighted = matVec(this.weights[i], activations);
      const withBias = weighted.map((value, idx) => value + this.biases[i][idx]);
      activations = applyActivationVector(withBias, this.layerSpecs[i].activation);
    }

    return activations;
  }
}

function randomMatrix(rows, cols, scale) {
  const out = [];
  for (let r = 0; r < rows; r += 1) {
    const row = [];
    for (let c = 0; c < cols; c += 1) {
      row.push((Math.random() * 2 - 1) * scale);
    }
    out.push(row);
  }
  return out;
}

function randomVector(size, scale) {
  const out = [];
  for (let i = 0; i < size; i += 1) {
    out.push((Math.random() * 2 - 1) * scale);
  }
  return out;
}

function matVec(matrix, vector) {
  return matrix.map((row) =>
    row.reduce((sum, value, idx) => sum + value * vector[idx], 0)
  );
}

function applyActivationVector(values, activationName) {
  if (activationName === "relu") {
    return values.map((v) => Math.max(0, v));
  }
  if (activationName === "sigmoid") {
    return values.map((v) => 1 / (1 + Math.exp(-v)));
  }
  if (activationName === "tanh") {
    return values.map((v) => Math.tanh(v));
  }
  if (activationName === "softmax") {
    const max = Math.max(...values);
    const exps = values.map((v) => Math.exp(v - max));
    const denom = exps.reduce((sum, v) => sum + v, 0);
    return exps.map((v) => v / denom);
  }
  return values;
}

function outputActivationForTask() {
  if (state.taskType === "regression") {
    return "linear";
  }
  return state.outputSize === 1 ? "sigmoid" : "softmax";
}

function parsePositiveNumber(value, fallback, min, max) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, parsed));
}

function syncGlobalControls() {
  state.inputSize = parsePositiveNumber(els.inputSize.value, state.inputSize, 1, 512);
  state.outputSize = parsePositiveNumber(els.outputSize.value, state.outputSize, 1, 128);
  state.learningRate = parsePositiveNumber(els.learningRate.value, state.learningRate, 0.00001, 1);
  state.taskType = els.taskType.value === "classification" ? "classification" : "regression";

  els.inputSize.value = String(state.inputSize);
  els.outputSize.value = String(state.outputSize);
  els.learningRate.value = String(state.learningRate);
}

function resetHiddenLayers() {
  state.hiddenLayers = [
    { id: 1, units: 8, activation: "relu" },
    { id: 2, units: 4, activation: "relu" }
  ];
  state.nextLayerId = 3;
}

function renderLayerList() {
  els.layerList.innerHTML = "";

  if (state.hiddenLayers.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No hidden layers. This will become logistic or linear regression.";
    els.layerList.appendChild(empty);
    return;
  }

  state.hiddenLayers.forEach((layer, index) => {
    const fragment = els.layerRowTemplate.content.cloneNode(true);
    const row = fragment.querySelector(".layer-row");
    const badge = fragment.querySelector(".layer-badge");
    const unitsInput = fragment.querySelector(".layer-units");
    const activationSelect = fragment.querySelector(".layer-activation");
    const removeBtn = fragment.querySelector(".remove-layer-btn");

    badge.textContent = `L${index + 1}`;
    unitsInput.value = String(layer.units);
    activationSelect.value = layer.activation;

    unitsInput.addEventListener("change", () => {
      layer.units = parsePositiveNumber(unitsInput.value, layer.units, 1, 2048);
      unitsInput.value = String(layer.units);
      buildModel("Updated hidden layer size.");
    });

    activationSelect.addEventListener("change", () => {
      layer.activation = activationSelect.value;
      buildModel("Updated activation.");
    });

    removeBtn.addEventListener("click", () => {
      state.hiddenLayers = state.hiddenLayers.filter((item) => item.id !== layer.id);
      renderLayerList();
      buildModel("Removed hidden layer.");
    });

    row.dataset.layerId = String(layer.id);
    els.layerList.appendChild(fragment);
  });
}

function compileModelConfig() {
  const outputActivation = outputActivationForTask();
  const sizes = [state.inputSize, ...state.hiddenLayers.map((layer) => layer.units), state.outputSize];
  const activations = [...state.hiddenLayers.map((layer) => layer.activation), outputActivation];
  const denseLayers = sizes.slice(0, -1).map((inputWidth, idx) => ({
    index: idx + 1,
    in: inputWidth,
    out: sizes[idx + 1],
    activation: activations[idx]
  }));

  const totalParams = denseLayers.reduce((sum, layer) => sum + layer.in * layer.out + layer.out, 0);

  return {
    schema_version: "0.0.1-browser-prototype",
    model_type: "dense_feed_forward",
    task_type: state.taskType,
    optimizer: {
      type: "sgd",
      learning_rate: state.learningRate
    },
    layers: denseLayers,
    summary: {
      hidden_layers: state.hiddenLayers.length,
      total_layers: denseLayers.length,
      trainable_params: totalParams
    }
  };
}

function drawNetwork(config) {
  const svg = els.networkCanvas;
  const width = Math.max(720, svg.clientWidth || 720);
  const height = 320;
  const padX = 70;
  const padY = 55;
  const sizes = [state.inputSize, ...state.hiddenLayers.map((layer) => layer.units), state.outputSize];
  const labels = ["Input", ...state.hiddenLayers.map((_, idx) => `Hidden ${idx + 1}`), "Output"];

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = "";

  const columns = [];
  const stepX = sizes.length > 1 ? (width - padX * 2) / (sizes.length - 1) : 0;

  sizes.forEach((units, idx) => {
    const x = padX + idx * stepX;
    const visible = Math.min(units, 8);
    const spread = Math.max(1, visible - 1);
    const nodeYs = Array.from({ length: visible }, (_, i) => padY + (i * (height - padY * 2)) / spread);
    columns.push({ x, nodeYs, units });
  });

  for (let i = 0; i < columns.length - 1; i += 1) {
    for (const srcY of columns[i].nodeYs) {
      for (const dstY of columns[i + 1].nodeYs) {
        svg.appendChild(
          createSvgNode("line", {
            x1: columns[i].x,
            y1: srcY,
            x2: columns[i + 1].x,
            y2: dstY,
            class: "edge"
          })
        );
      }
    }
  }

  columns.forEach((column, idx) => {
    const title = createSvgNode("text", { x: column.x, y: 20, class: "layer-title" });
    title.textContent = `${labels[idx]} (${column.units})`;
    svg.appendChild(title);

    if (column.units > column.nodeYs.length) {
      const extra = createSvgNode("text", { x: column.x, y: 34, class: "layer-extra" });
      extra.textContent = `+${column.units - column.nodeYs.length} more`;
      svg.appendChild(extra);
    }

    for (const y of column.nodeYs) {
      svg.appendChild(createSvgNode("circle", { cx: column.x, cy: y, r: 8, class: "node" }));
    }
  });

  els.paramCount.textContent = formatNumber(config.summary.trainable_params);
  els.layerCount.textContent = String(config.summary.total_layers);
  els.outputActivation.textContent = outputActivationForTask();
}

function createSvgNode(tag, attrs) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(value);
}

function buildModel(statusMessage) {
  syncGlobalControls();
  const config = compileModelConfig();
  state.model = new SimpleDenseNetwork(config.layers);

  renderLayerList();
  drawNetwork(config);
  renderJson(config);
  updateInputHint();
  setStatus(statusMessage || "Model rebuilt.");
}

function updateInputHint() {
  const placeholders = Array.from({ length: state.inputSize }, () => Number((Math.random() * 2 - 1).toFixed(3)));
  if (!els.inputVector.value.trim()) {
    els.inputVector.value = placeholders.join(", ");
  }
}

function parseInputVector(rawText) {
  const numbers = rawText
    .split(/[,\s]+/)
    .map((v) => v.trim())
    .filter(Boolean)
    .map((v) => Number(v));

  if (numbers.length !== state.inputSize || numbers.some((v) => !Number.isFinite(v))) {
    throw new Error(`Expected ${state.inputSize} numeric values.`);
  }

  return numbers;
}

function runInference() {
  if (!state.model) {
    buildModel("Model initialized before inference.");
  }

  try {
    const vector = parseInputVector(els.inputVector.value);
    const output = state.model.forward(vector);

    const body = {
      input: vector,
      output: output.map((v) => Number(v.toFixed(6))),
      output_activation: outputActivationForTask()
    };
    els.inferenceOutput.textContent = JSON.stringify(body, null, 2);
    setStatus("Forward pass complete.");
  } catch (error) {
    els.inferenceOutput.textContent = `Input error: ${error.message}`;
    setStatus("Fix input vector length and values.");
  }
}

function fillRandomInput() {
  const values = Array.from({ length: state.inputSize }, () => Number((Math.random() * 2 - 1).toFixed(4)));
  els.inputVector.value = values.join(", ");
  setStatus("Random input generated.");
}

function renderJson(config) {
  els.modelJson.textContent = JSON.stringify(config, null, 2);
}

async function copyJson() {
  try {
    await navigator.clipboard.writeText(els.modelJson.textContent);
    setStatus("Model JSON copied.");
  } catch (_error) {
    setStatus("Clipboard not available in this browser context.");
  }
}

function setStatus(text) {
  els.builderStatus.textContent = text;
}

function setupEvents() {
  els.addLayerBtn.addEventListener("click", () => {
    state.hiddenLayers.push({ id: state.nextLayerId, units: 8, activation: "relu" });
    state.nextLayerId += 1;
    renderLayerList();
    buildModel("Added hidden layer.");
  });

  els.resetBtn.addEventListener("click", () => {
    resetHiddenLayers();
    renderLayerList();
    buildModel("Architecture reset.");
  });

  els.buildBtn.addEventListener("click", () => buildModel("Model rebuilt from controls."));
  els.inferBtn.addEventListener("click", runInference);
  els.randomInputBtn.addEventListener("click", fillRandomInput);
  els.copyBtn.addEventListener("click", copyJson);

  [els.inputSize, els.outputSize, els.learningRate, els.taskType].forEach((control) => {
    control.addEventListener("change", () => buildModel("Updated global config."));
  });

  window.addEventListener("resize", () => {
    if (!state.model) {
      return;
    }
    drawNetwork(compileModelConfig());
  });
}

function init() {
  resetHiddenLayers();
  renderLayerList();
  setupEvents();
  buildModel("Neural net builder ready.");
}

init();
