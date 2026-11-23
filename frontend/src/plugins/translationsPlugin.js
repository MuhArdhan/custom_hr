import { indonesianMessages } from "./indonesianMessages.js"

export const LANGUAGE_KEY = "custom_hr:language"
export function getLanguage() {
	try {
		return localStorage.getItem(LANGUAGE_KEY) === "en" ? "en" : "id"
	} catch {
		return "id"
	}
}

export function setLanguage(value) {
	if (value !== "id" && value !== "en") return
	localStorage.setItem(LANGUAGE_KEY, value)
	window.location.reload()
}

function makeTranslationFunction() {
	let messages = {};
	return {
		translate,
		load: () => Promise.allSettled([
			setup(),
			// TODO: load dayjs locales
		]),
	}

	async function setup() {
		if (window.frappe?.boot?.__messages) {
			messages = window.frappe?.boot?.__messages;
			return;
		}
	}

	function translate(txt, replace, context = null) {
		if (!txt || typeof txt != "string") return txt;
		if (getLanguage() === "en") return replace && typeof replace === "object" ? format(txt, replace) : txt;

		let translated_text = "";
		let key = txt;
		if (context) {
			translated_text = indonesianMessages[`${key}:${context}`] || messages[`${key}:${context}`];
		}
		if (!translated_text) {
			translated_text = indonesianMessages[key] || messages[key] || txt;
		}
		if (replace && typeof replace === "object") {
			translated_text = format(translated_text, replace);
		}

		return translated_text;
	}

	function format(str, args) {
		if (str == undefined) return str;

		let unkeyed_index = 0;
		return str.replace(
			/\{(\w*)\}/g,
			(match, key) => {
				if (key === "") {
					key = unkeyed_index;
					unkeyed_index++;
				}
				if (key == +key) {
					return args[key] !== undefined ? args[key] : match;
				}
				return args[key] !== undefined ? args[key] : match;
			}
		);
	}
}

const { translate, load } = makeTranslationFunction();
export const __ = translate;

export const translationsPlugin = {
	async isReady() {
		await load();
	},
	install(/** @type {import('vue').App} */ app, options) {
		const __ = translate;
		// app.mixin({ methods: { __ } })
		app.config.globalProperties.__ = __;
		app.provide("$translate", __);
	},
}
