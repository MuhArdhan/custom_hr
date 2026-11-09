import * as faceapi from "@vladmandic/face-api"

export const FACE_MODELS_URL = "/assets/custom_hr/face/models"

let modelsPromise = null

export function loadFaceModels() {
	if (!modelsPromise) {
		modelsPromise = Promise.all([
			faceapi.nets.tinyFaceDetector.loadFromUri(FACE_MODELS_URL),
			faceapi.nets.faceLandmark68Net.loadFromUri(FACE_MODELS_URL),
			// no faceRecognitionNet: the server computes the descriptor from faceImage()
		])
			.then(async () => {
				try {
					await faceapi.tf.setBackend("webgl")
					await faceapi.tf.ready()
				} catch (error) {
					// fall back to the default backend (cpu)
				}
				return faceapi
			})
			.catch((error) => {
				modelsPromise = null
				throw error
			})
	}
	return modelsPromise
}

// lightweight options for the live "face present" indicator
export const detectorOptions = () =>
	new faceapi.TinyFaceDetectorOptions({ inputSize: 160, scoreThreshold: 0.5 })

// higher resolution options for enrollment/verification captures: better landmarks
// mean better face alignment and a more discriminative face descriptor on the server
export const captureDetectorOptions = () =>
	new faceapi.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.5 })

// Android drops the page's GPU context while a native camera app holds the screen;
// webgl then never answers (detection hangs), so carry on with the cpu backend.
export async function ensureLiveBackend() {
	if (faceapi.tf.getBackend() === "webgl" && faceapi.tf.backend().gpgpu?.gl?.isContextLost?.()) {
		await faceapi.tf.setBackend("cpu")
		await faceapi.tf.ready()
	}
}

// generous for slow phones (first run compiles the GPU programs); only stops an endless spinner
export const DETECTION_TIMEOUT_MS = 30000

export function withTimeout(promise, ms = DETECTION_TIMEOUT_MS) {
	let timer
	const timeout = new Promise((_, reject) => {
		timer = setTimeout(() => reject(new Error("Face detection timed out")), ms)
	})
	return Promise.race([promise, timeout]).finally(() => clearTimeout(timer))
}

export async function detectFace(input) {
	await ensureLiveBackend()
	return await withTimeout(faceapi.detectSingleFace(input, captureDetectorOptions()).withFaceLandmarks())
}

// The aligned face exactly as withFaceDescriptor() hands it to the recognition net: the dlib
// alignment box (not alignedRect), squared to 150px, PNG so no pixel changes.
// custom_hr.services.face_descriptor turns it into the 128-value descriptor.
export async function faceImage(input, detection) {
	const box = detection.landmarks.align(null, { useDlibAlignment: true })
	const [face] = await faceapi.extractFaces(input, [box])
	return faceapi.imageToSquare(face, 150, true).toDataURL("image/png")
}

export function snapshotCanvas(input, width = 640) {
	const sourceWidth = input.videoWidth || input.naturalWidth || input.width || width
	const sourceHeight = input.videoHeight || input.naturalHeight || input.height || width
	const canvas = document.createElement("canvas")
	canvas.width = width
	canvas.height = Math.max(1, Math.round((sourceHeight / sourceWidth) * width))
	canvas.getContext("2d").drawImage(input, 0, 0, canvas.width, canvas.height)
	return canvas
}

// Front cameras can deliver a mirrored frame: flip only the kept photo. faceImage must keep the raw frame.
export function mirroredPhoto(source) {
	const canvas = document.createElement("canvas")
	canvas.width = source.width
	canvas.height = source.height
	const context = canvas.getContext("2d")
	context.translate(source.width, 0)
	context.scale(-1, 1)
	context.drawImage(source, 0, 0)
	return canvas.toDataURL("image/jpeg", 0.8)
}

export function capturePhoto(input, width = 480) {
	return snapshotCanvas(input, width).toDataURL("image/jpeg", 0.8)
}
