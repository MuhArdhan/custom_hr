const routes = [
	{
		name: "GroomingView",
		path: "/grooming",
		component: () => import("@/views/grooming/Grooming.vue"),
	},
	{
		name: "GroomingDetailView",
		path: "/grooming/:id",
		props: true,
		component: () => import("@/views/grooming/Detail.vue"),
	},
]

export default routes
