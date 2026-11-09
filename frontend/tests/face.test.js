import test from "node:test"
import assert from "node:assert/strict"
import path from "node:path"
import { fileURLToPath } from "node:url"
import vm from "node:vm"
import { build } from "esbuild"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const bundle = await build({
	entryPoints: [path.join(root, "src/utils/face.js")], bundle: true, write: false, format: "cjs", platform: "node",
	plugins: [{ name: "face-api-mock", setup(b) {
		b.onResolve({ filter: /^@vladmandic\/face-api$/ }, () => ({ path: "face-api", namespace: "mock" }))
		b.onLoad({ filter: /.*/, namespace: "mock" }, () => ({ contents: "module.exports = globalThis.__faceapi", loader: "js" }))
	} }],
})

function load(contextLost) {
	const calls = []
	let backend = "webgl"
	const faceapi = {
		TinyFaceDetectorOptions: class {},
		tf: {
			getBackend: () => backend,
			backend: () => ({ gpgpu: { gl: { isContextLost: () => contextLost } } }),
			setBackend: async (name) => { calls.push(`setBackend:${name}`); backend = name },
			ready: async () => {},
		},
		detectSingleFace: () => {
			calls.push(`detect:${backend}`)
			return { withFaceLandmarks: async () => "face" }
		},
		nets: Object.fromEntries(["tinyFaceDetector", "faceLandmark68Net", "faceRecognitionNet"].map((name) => [name, { loadFromUri: async () => calls.push(`load:${name}`) }])),
		extractFaces: async (input, boxes) => { calls.push(`extract:${input}:${boxes[0]}`); return ["crop"] },
		imageToSquare: (image, size, centered) => ({ toDataURL: (type) => `${type}|${image}|${size}|${centered}` }),
	}
	const module = { exports: {} }
	const document = { createElement: () => ({ getContext: () => ({
		translate: (x, y) => calls.push(`translate:${x}:${y}`), scale: (x, y) => calls.push(`scale:${x}:${y}`), drawImage: (s) => calls.push(`draw:${s.id}`),
	}), toDataURL: (type) => type }) }
	vm.runInNewContext(bundle.outputFiles[0].text, { module, exports: module.exports, setTimeout, clearTimeout, document, globalThis: { __faceapi: faceapi } })
	return { face: module.exports, calls }
}

test("detectFace moves to the cpu backend once the webgl context is lost (native camera app)", async () => {
	const { face, calls } = load(true)
	assert.equal(await face.detectFace({}), "face")
	assert.deepEqual(calls, ["setBackend:cpu", "detect:cpu"])
})

test("detectFace keeps webgl while its context is alive", async () => {
	const { face, calls } = load(false)
	assert.equal(await face.detectFace({}), "face")
	assert.deepEqual(calls, ["detect:webgl"])
})

test("loadFaceModels loads only the detector and landmark nets: the server computes descriptors", async () => {
	const { face, calls } = load(false)
	await face.loadFaceModels()
	assert.deepEqual(calls.filter((c) => c.startsWith("load:")).sort(), ["load:faceLandmark68Net", "load:tinyFaceDetector"])
})

test("faceImage crops the dlib-aligned face to a 150px square png, the way withFaceDescriptor feeds its recognition net", async () => {
	const { face, calls } = load(false)
	const aligns = []
	const detection = { alignedRect: "min-bbox", landmarks: { align: (box, options) => { aligns.push([box, options.useDlibAlignment]); return "dlib-box" } } }
	assert.equal(await face.faceImage("frame", detection), "image/png|crop|150|true")
	assert.deepEqual(aligns, [[null, true]])
	assert.deepEqual(calls, ["extract:frame:dlib-box"])
})

test("withTimeout ends a detection that never answers, and passes a quick one through", async () => {
	const { face } = load(false)
	await assert.rejects(face.withTimeout(new Promise(() => {}), 20), /timed out/)
	assert.equal(await face.withTimeout(Promise.resolve("face"), 20), "face")
})

test("mirroredPhoto flips the kept photo around its width and leaves the source frame alone", () => {
	const { face, calls } = load(false)
	const source = { id: "frame", width: 640, height: 480 }
	assert.equal(face.mirroredPhoto(source), "image/jpeg")
	assert.deepEqual(calls, ["translate:640:0", "scale:-1:1", "draw:frame"])
	assert.equal(source.width, 640)
})
