export const imageGroups={
  generate:[
    ["Nano Banana 2 Lite - Generate","Google's Gemini 3.1 Flash Lite - Ultra-fast text-to-image generation at low cost","Best"],
    ["ImageGen 3","Advanced model for detailed text-to-image creation",""],
    ["Nano Banana 2 - Generate","Google's Gemini 3.1 Flash - Fast text-to-image generation with 0.5K-4K resolution","Pro Model"],
    ["Nano Banana Pro - Generate","Google's Gemini 3 Pro - High-quality text-to-image generation with advanced resolution control","Pro Model"],
    ["Nano Banana - Generate","Google's Gemini 2.5 Flash - Fast and affordable text-to-image generation",""],
    ["GPT Image 2","OpenAI's GPT Image 2 - Next-gen image generation with variable quality and flexible sizing","Pro Model"],
    ["GPT Image 2.5 Flare","OpenAI's GPT Image 2.5 Flare - Higher quality than GPT Image 2 at up to 50% lower latency","Pro Model"],
    ["GPT Image 2.5 Sunburst","OpenAI's GPT Image 2.5 Sunburst - Most capable model for premium, detail-critical work","Pro Model"],
    ["SeedDream v5 Lite - Generate","ByteDance SeedDream v5 Lite - High-quality 2K-3K image generation with multi-reference blending",""],
    ["Seedream 5 Pro","ByteDance Seedream 5 Pro - Flagship precision creation with complex infographics and native text rendering",""],
    ["Flux 2","Latest Flux 2 model with native multi-image support, guidance control, and acceleration options","Top Choice"],
    ["Flux 2 Flex","Flux 2 Flex model with advanced guidance control and inference step customization","New"],
    ["Flux 2 Pro","Flux 2 Pro model optimized for high-quality professional image generation","Pro Model"],
    ["ImageGen 3 Fast","Faster version of ImageGen 3 with quicker generation times",""],
    ["Flux","Generate images quickly from text prompts","Top Choice"],
    ["Flux Pro","High-quality professional text-to-image generation","Pro Model"],
    ["Flux Dev","Fast version with enhanced image fidelity",""],
    ["GPT-Image-1","OpenAI's latest text-to-image model with variable quality & size",""]
  ],
  edit:[
    ["GPT Image 2 Edit","OpenAI GPT Image 2 - prompt-based image editing","Pro Model"],
    ["GPT Image 2.5 Flare Edit","OpenAI GPT Image 2.5 Flare - fast high-quality editing","Pro Model"],
    ["GPT Image 2.5 Sunburst Edit","OpenAI GPT Image 2.5 Sunburst - premium detail-critical editing","Pro Model"],
    ["Nano Banana 2 - Edit","Google Gemini 3.1 Flash - multi-image Gemini editing",""],
    ["Nano Banana Pro - Edit","Google Gemini 3 Pro - premium Gemini editing","Pro Model"],
    ["Gemini Edit","Multi-image editing","Top Choice"],
    ["Flux 2 Edit","Advanced editing with multiple inputs","New"],
    ["Flux 2 Flex Edit","Guidance-controlled Flux editing","New"],
    ["SeedDream v5 Lite Edit","High-quality guided editing",""]
  ],
  convert:[
    ["Convert Anything","Transform photos into any requested style",""],
    ["Parts Sheet","Generate exploded-view component diagrams",""],
    ["Bust Maker","Create museum-style busts",""],
    ["Table-top Figurine","Turn portraits into collectible figurines",""],
    ["Pose Generator","Convert characters into T-pose or A-pose","Popular"],
    ["Fantasy Character","Fantasy RPG concept art",""],
    ["Stylized 3D Render","Vibrant stylized 3D renders","Popular"],
    ["Anime Character","Cel-shaded anime illustrations",""],
    ["Ghibli Art","Warm painterly animation-inspired scenes",""]
  ],
  "image-reference":[
    ["Nano Reference","Use multiple photos for style and composition",""],
    ["Image Reference","Blend visual elements and colors",""],
    ["Style Transfer","Transfer stylistic details",""],
    ["Character Sheet","Create a four-view turnaround",""]
  ],
  "style-reference":[
    ["Custom Style Reference","Upload up to 10 images to define a style","Popular"],
    ["Medieval Strategy Style","Colorful medieval fantasy art","Example"],
    ["Battle Royale Style","Bold cartoon action scenes","Example"],
    ["Stylized Character Style","Polished 3D character rendering","Example"],
    ["Miniature Architecture Style","Miniature architectural look","Example"]
  ],
  sketch:[
    ["Sketch -> Image","Turn line art into a rendered image",""],
    ["Paint & Transform","Transform rough paint into final art",""]
  ],
  utilities:[
    ["Remove Background","Erase the background, keep the subject","Popular"],
    ["Upscale (Creative)","2x-4x creative upscale",""],
    ["Upscale (Clarity)","Detail-preserving upscale",""],
    ["Upscale (Fast)","Fast super-resolution",""],
    ["Crop Image","Crop and adjust dimensions",""],
    ["Restore Lighting","Remove shadows and baked-in lighting","Ideal for 3D"]
  ],
  video:[
    ["Video has moved to the new Video Studio","Open /VideoStudio for the full video workspace",""],
    ["Veo 3 Fast (Image to Video)","Animate images into clips",""],
    ["Veo 3 Fast (Text to Video)","Generate video from text",""],
    ["Kling (Image to Video)","Prompt-controlled motion",""],
    ["Veo 3 Standard (Image to Video)","Premium image animation","Pro Model"],
    ["Lucy 14B (Image to Video)","Open-source style image-to-video",""],
    ["Seedance 1.5 Pro (Image to Video)","Flexible premium video generation","Pro Model"],
    ["Kling O1 (Frame Transition)","Frame-to-frame motion control",""]
  ]
};

export const categories=[
  ["generate","Generate"],["edit","Edit"],["convert","Convert"],["image-reference","Image Reference"],
  ["style-reference","Style Reference"],["sketch","Sketch"],["utilities","Image Tools"],["video","Video"]
];

export const modelCatalog=[
  ["Prism 3.1","3D AI Studio","Best overall - strongest textures and geometry","35 cr","3-5 min","8K · Quad · PBR","RECOMMENDED"],
  ["Hunyuan 3.1 Pro","Tencent","Sharpest edges - best for hard-surface shapes","40 cr","3-4 min","4K · PBR",""],
  ["Tripo P2 - Game Ready","Tripo","Game-ready topology - native quad output","70 cr","1-3 min","Quad · 4K","BETA"],
  ["Meshy 7.1","Meshy","Ultra 4K geometry and up to 8K textures","40 cr","5-10 min","8K · PBR · Pose","NEW"],
  ["Meshy - Game Ready","Meshy","Low-poly quad output up to 15k polys","20 cr","5-10 min","Quad · Pose","NEW"],
  ["Rodin 2.5","Hyper3D","Five quality tiers with scalable cost","30 cr","6-7 min","PBR · 4K",""],
  ["Forge Gen-2","3D AI Studio","Extensive controls and PBR output","35 cr","5-7 min","PBR · 4K",""],
  ["Trellis 2","Microsoft","Thin/open shapes and budget workflows","15 cr","4-8 min","PBR · 4K",""],
  ["Hitem3D 3.0","Hitem3D","Watertight meshes for 3D printing","115 cr","2-20 min","3D-Print · PBR","NEW"],
  ["Miora3D 1.0","Tencent","True-to-photo products, strong text/labels","40 cr","2-5 min","PBR","NEW"],
  ["Seed3D 1.0","ByteDance","Experimental advanced-user model","30 cr","8-12 min","","BETA"]
];

export const toolboxGroups=[
  ["MATERIAL TOOLS",[
    ["Material AI","/Tools/MaterialGenerator"],["Seamless Texture AI","/Tools/SeamlessTextureGenerator"],["PBR Extract AI","/Tools/PBRMapGenerator"]
  ]],
  ["IMAGE TOOLS",[
    ["Character Sheet","/Tools/CharacterSheetGenerator"],["Split Image into Parts","/Tools/SplitImageIntoParts"],["AI Pose Transfer","/Tools/PoseTransfer"],["Image to Prompt","/Tools/ImageToPrompt"]
  ]],
  ["3D CREATORS",[
    ["SVG to 3D","/svgTo3D","FREE"],["3D Text","/font3d","FREE"],["Relief Generator","/Tools/3DReliefGenerator"]
  ]],
  ["3D PROCESSING",[
    ["Rigging & Animation","/Tools/RiggingTool"],["Segmentation Tool","/Tools/SegmentationTool"],["UV Unfold","/Tools/UVUnfold","BETA"],["Remesh Tool","/Tools/Remesh"]
  ]],
  ["MODEL UTILITIES",[
    ["3D Viewer","/Tools/Viewer3D"],["Model Spinner","/Tools/GLBVideoRenderer","FREE"],["GLB Compression","/Tools/GLBCompression","FREE"],["Add Base","/Tools/AddBase","FREE"],["Vertex Color","/Tools/VertexColor","FREE"],["3D Stager","/Tools/ThreeDStager"]
  ]],
  ["GAUSSIAN SPLATS",[
    ["Image to Splat","/ImageToGaussianSplat"],["Splat Viewer","/GaussianSplatViewer","FREE"]
  ]],
  ["VIDEO",[
    ["Image to Video","/Tools/VideoGen"]
  ]],
  ["HELPER TOOLS",[
    ["Prompt Helper","/Tools/PromptHelper"],["Audio Generation","/Tools/Audio"]
  ]]
];

export const toolPages={
  MaterialGenerator:{
    title:"AI Material Generator",
    subtitle:"Create PBR materials with base color, normal, roughness, metalness & height maps",
    kind:"material",
    tabs:["Describe Material","Extract from Photo","Image to Maps"],
    tabHints:["Generate material & maps from a prompt","Extract a material from a photo region","Predict PBR maps from an existing image"],
    presets:["Brushed Steel","Worn Leather","Mossy Stone","Red Brick","Oak Wood","Concrete"],
    options:["Base Color","Normal","Roughness","Metalness","Height","Upscale (Higher Resolution) Pro"],
    labels:["Creation Method","Material Description","Output Maps"],
    placeholder:"Describe the material, e.g. \"brushed copper with green patina\", \"worn concrete with cracks\"",
    previewTabs:["Material Preview","All Maps","Tiling Check"],
    action:"Create Material",
    extras:["ADVANCED","Frequently Asked Questions","Try this prompt →"]
  },
  SeamlessTextureGenerator:{
    title:"Seamless Texture Generator",
    subtitle:"Generate seamless, tileable textures with AI-powered PBR material maps",
    kind:"material",
    tabs:["Text to Material","Image to Material"],
    tabHints:["Generate texture & maps from a prompt","Predict PBR maps from an image"],
    options:["Base Color","Normal","Roughness","Metalness","Height","Both","Horizontal","Vertical"],
    labels:["Generation Mode","Prompt","PBR Maps","Tiling Mode"],
    placeholder:"Describe the texture, e.g. \"weathered red brick wall\", \"polished marble with grey veins\"",
    previewTabs:["Seamless Preview","3D Preview","All Maps"],
    action:"Generate Material",
    extras:["Upscale PBR Maps Pro","ADVANCED","FAQ"]
  },
  PBRMapGenerator:{
    title:"Image to PBR Maps",
    subtitle:"Generate normal, roughness, height and more maps from any image",
    kind:"upload_maps",
    labels:["Source Image REQUIRED","Map Type","AI Model"],
    options:["Normal Map","Roughness Map","Height Map","Ambient Occlusion","Metallic Map","Depth Map"],
    models:["Nano Banana 2 10 cr","Gemini Edit 6 cr","Nano Banana Pro 14 cr"],
    previewTabs:["All","Normal","Roughness","Height","Depth","Metallic"],
    action:"Generate Normal Map",
    uploadHint:"Drag & drop or click to upload PNG, JPG, WebP up to 10MB · Ctrl+V to paste"
  },
  CharacterSheetGenerator:{
    title:"AI character sheet generator",
    subtitle:"Upload one character image and get consistent front, left, right and back views. Split them into separate images, or turn them into a 3D model.",
    kind:"steps_upload",
    tagline:"One image in, four views out",
    steps:["1. Upload a character","2. Generate the views","3. Split or go 3D"],
    action:"Let's go",
    ctaUpload:"Choose from Dashboard"
  },
  SplitImageIntoParts:{
    title:"Split any image into parts with AI",
    subtitle:"Upload one image and the AI finds its separable parts, then cuts each one out as its own image.",
    kind:"steps_upload",
    tagline:"One image in, every part out",
    steps:["1. Analyze","2. Review","3. Extract"],
    action:"Let's go",
    ctaUpload:"Choose from Dashboard"
  },
  PoseTransfer:{
    title:"AI Pose Changer",
    subtitle:"Change poses in your photos with AI",
    kind:"pose",
    labels:["Source Image","Reference Pose","AI Model","Quality","Resolution","Additional Instructions"],
    options:["Select from Pose Library","Upload Your Own Pose Reference Image","Low","Medium","High","1K","2K","4K","Nano Banana 2","Gemini Edit","Nano Banana Pro","GPT Image 2"],
    action:"Apply Pose",
    ctaUpload:"Choose from Dashboard"
  },
  ImageToPrompt:{
    title:"Image to Prompt",
    subtitle:"Upload an image to generate a detailed AI-ready text description",
    kind:"marketing_upload",
    sections:["How it works","FAQ","Get started"],
    uploadHint:"Drop your image here or click to browse PNG, JPG, WebP · Max 5 MB",
    action:"Generate Prompt"
  },
  "3DReliefGenerator":{
    title:"3D Relief Generator",
    subtitle:"Transform any image into a 3D printable relief sculpture",
    kind:"steps_upload",
    steps:["1. Upload image","2. AI generates depth","3. Export 3D model"],
    action:"Generate Relief"
  },
  RiggingTool:{
    title:"AI Rigging & Animation",
    subtitle:"Upload a GLB model to add AI-powered rigging and animation",
    kind:"marketing_upload",
    uploadHint:"Drop your GLB file here or click to browse GLB format · Biped · T-pose",
    options:["Biped","Quadruped","Hexapod","Avian","Serpentine","Aquatic","Walk","Run","Jump","Dance","Combat"],
    action:"Auto-Rig Model"
  },
  SegmentationTool:{
    title:"AI Mesh Segmentation",
    subtitle:"Upload a 3D model to automatically split it into logical parts - with optional printable joints for 3D printing",
    kind:"marketing_upload",
    action:"Segment Model"
  },
  UVUnfold:{
    title:"AI UV Unfold",
    subtitle:"Generate clean, optimized UV layouts for your 3D models - see the result before you download",
    kind:"marketing_upload",
    uploadHint:"Drop your 3D model here or click to browse",
    action:"Generate UV Layout",
    ctaUpload:"Choose from Dashboard Pro"
  },
  Remesh:{
    title:"Remesh 3D Model",
    subtitle:"Upload a GLB file to optimize mesh topology and reduce polygon count",
    kind:"marketing_upload",
    uploadHint:"Drop your GLB file here or click to browse GLB format only",
    options:["Prism","Pro","Hunyuan","Triangles","Quads","GLB","FBX","OBJ","STL","BLEND","USDZ"],
    action:"Remesh Model"
  },
  Viewer3D:{
    title:"3D Viewer",
    subtitle:"Drop any 3D model to view · FREE · 100% client-side",
    kind:"viewer",
    uploadHint:"Drag a GLB · GLTF · FBX · OBJ · STL file anywhere — your file never leaves the browser",
    cameras:["F","B","L","R","T","Bo","Iso"],
    tabs:["Model","Display","Environment","Lighting","Camera","Scene","Export"],
    options:["Original","Wireframe","Clay","X-Ray","Normals","Transparent"],
    env:["STUDIO","SUNSET","FOREST","APARTMENT","NIGHT"],
    labels:["OVERRIDE TEXTURE (PNG/JPG)","MATERIAL MODE","BACKGROUND","HDRI PRESET","ENVIRONMENT INTENSITY"],
    formats:["GLB","GLTF","FBX","OBJ","STL"],
    action:"Upload a 3D file"
  },
  GLBVideoRenderer:{
    title:"360 Video Renderer",
    subtitle:"Create turntable videos from 3D models · WebM with Alpha",
    kind:"model_settings",
    labels:["Resolution","FPS","Duration","Material","Brightness"],
    optionGroups:{
      "Resolution":["480p","720p","1080p","2K","4K"],
      "FPS":["24","30","60"],
      "Duration":["3s","5s","8s","10s"],
      "Material":["Mesh","Color","PBR"]
    },
    action:"Render Video",
    ctaUpload:"Choose from Dashboard"
  },
  GLBCompression:{
    title:"GLB Compressor",
    subtitle:"Reduce 3D model file sizes by up to 90% · New Release - In Beta",
    kind:"model_settings",
    options:["Balanced","Maximum","Fast","Minimal"],
    action:"Compress",
    extras:["Advanced Settings","Feedback","FAQ"],
    ctaUpload:"Choose from Dashboard"
  },
  AddBase:{
    title:"Add Base",
    subtitle:"Add professional pedestals to your 3D models · New Release - In Beta",
    kind:"model_upload",
    action:"Add Base",
    ctaUpload:"Choose from Dashboard Pro"
  },
  VertexColor:{
    title:"Texture to Vertex Color",
    subtitle:"Convert textures to vertex colors for multi-color 3D printing · Free Tool",
    kind:"model_upload",
    options:["Full Color","Palette Reduction","OBJ","GLB"],
    action:"Convert to Vertex Colors",
    ctaUpload:"Choose from Dashboard Pro"
  },
  ThreeDStager:{
    title:"GLB Renderer",
    subtitle:"Render 3D models online in any scene",
    kind:"stager",
    labels:["3D Models 0/5","Background Image Optional","Render Settings","Creativity Level","Render Style","Lighting","Environment","Surface/Ground","Effects","Scene Instructions","AI Model"],
    modes:["Guided","Custom"],
    creativity:["Faithful","Balanced","Creative"],
    styles:["Photorealistic","Cinematic","Product Shot","Architectural","Stylized Art","Anime/Toon","Fantasy","Sci-Fi"],
    effects:["Atmospheric Effects","Depth of Field","Enhanced Reflections","Particles/Dust","Volumetric Light"],
    models:["Nano Banana 2 Fast, high quality","Gemini Edit Fast, balanced quality","Nano Banana Pro Highest quality results"],
    action:"Capture & Render",
    cost:"4 credits",
    ctaUpload:"Choose from Dashboard"
  },
  VideoGen:{
    title:"AI Video Generation",
    subtitle:"Create Stunning Videos from Text & Images",
    kind:"marketing",
    actions:["Try Video AI","Start Creating Videos","Try Text to Video","Try Image to Video","Try Reference to Video","Open Image Studio"]
  },
  PromptHelper:{
    title:"Prompt Helper",
    subtitle:"What would you like to create?",
    kind:"prompt_helper",
    buttons:["No Project","New Image Prompt","Balanced","Library Beta"],
    chips:["Game character","Stylized weapon","Photorealistic","Isometric room"],
    hint:"Describe your idea in plain language - like you're talking to a friend. Bob will build the prompt."
  },
  Audio:{
    title:"Audio Generation",
    subtitle:"Convert text to natural-sounding speech with AI",
    kind:"audio",
    labels:["TEXT TO SPEAK","MODEL","VOICE","LANGUAGE"],
    options:["Multilingual v2 5c · Recommended","v3 Alpha 5c · New","Turbo v2.5 3c · Fast","Flash v2.5 3c · Fastest","Lily","Auto-detect"],
    action:"Generate Speech",
    extras:["Examples"]
  }
};
export const settingTabs=[
  "Profile","Billing & Credits","Team","Security","Passkeys & 2FA",
  "Appearance & Behavior","Notifications & Sound","Connect & Export","AI Assistants (MCP)","Help & About"
];

export const communitySamples3D=[
  ["HUNYUAN 3D V3.1","Goliath Paladin Oath of the Watcher","@themuffinman"],
  ["PRISM 3.1","Young girl with magic staff and potions.","@Jan"],
  ["PRISM 3.1 MULTI-IMAGE","Stone pizza oven with arched openings.","@Pizza Brick Oven"],
  ["MESHY 6","Mind Flayer from Barrier Peaks","@General Colt"],
  ["PRISM 3.1","Futuristic sci-fi gun with intricate details.","@Jan"],
  ["HUNYUAN 3D V3.1","Napster <3","@Nova Nexus"]
];
export const communitySamples2D=[
  ["GEMINI PRO EDIT","Still here.","@Nova Nexus"],
  ["GPT IMAGE 2 EDIT","Mounted sea elf officer","@Balciar"],
  ["BG REMOVAL V2","Inca priest","@Balciar"],
  ["IMAGEN 4","stylized 3d warrior in pixar style with an axe","@Jan"],
  ["GPT IMAGE 2 EDIT","generate a dagger in this fantasy style","@Jan"],
  ["IMAGEN 4 FAST","Spirit Miniatures for battletop wargame","@Lucius"]
];


export const tutorials=[
  {badge:"DOCUMENTATION",meta:"Guides · All Levels",title:"3D AI Studio Documentation - Complete Guide to Every Tool",desc:"Full documentation covering every tool, workflow, and feature in 3D AI Studio."},
  {badge:"MCP",meta:"5:29 · Workflow · Intermediate",title:"I Gave Claude a 3D Model MCP Server… Here's What It Built",desc:"See how Building Aeon combines the 3D AI Studio MCP server with Blender MCP and Claude Code."},
  {badge:"NEW",meta:"2:41 · Workflow · Beginner",title:"Sketch to 3D: Turn Any Drawing into a 3D Model (2-Minute Workflow)",desc:"Photograph your drawing, render clean concept art, then convert it."},
  {badge:"Quick Guide",meta:"Beginner · Beginner",title:"Get Way Better Results with 3D AI Studio - Quick Guide",desc:"Learn how to get the best possible results from 3D AI Studio."},
  {badge:"Full Guide",meta:"Workflow · Intermediate",title:"AI 3D Models for Games: Full Pipeline from Generation to Engine (2026)",desc:"The complete 2026 pipeline for turning AI-generated 3D models into production-ready game assets."},
  {badge:"COURSE",meta:"8 lessons · Beginner",title:"Beginner Course: Idea to 3D Model in Minutes (8 Episodes)",desc:"Complete beginner course by Gesa Pickbrenner (Phialo Design)."},
  {badge:"COURSE",meta:"7 lessons · All Levels",title:"Flow: Complete Tutorial Series (7 Parts)",desc:"The full Flow course - blank canvas to reusable AI apps."},
  {badge:"Part 1",meta:"Flow · Beginner",title:"Flow Part 1: Canvas Tour & Your First AI Image",desc:"Your tour of the Flow canvas - toolbar, fast vs sharp mode, node menu."},
  {badge:"Part 2",meta:"Flow · Beginner",title:"Flow Part 2: Turn Any Image into a 3D Model",desc:"Turn your generated image into a real 3D model."},
  {badge:"Part 3",meta:"Flow · Intermediate",title:"Flow Part 3: Consistent 3D Edits from Every Angle",desc:"Overhaul a 3D model and keep it consistent from every angle."},
  {badge:"Part 4",meta:"Flow · Intermediate",title:"Flow Part 4: Turn Any Flow into a Reusable App",desc:"Promote a node to a workflow input and mark a workflow output."},
  {badge:"Part 5",meta:"Flow · Intermediate",title:"Flow Part 5: Asset Packs with Batch & Style Reference",desc:"Combine Batch node with Style Reference to generate matching assets."},
  {badge:"Part 6",meta:"Flow · Beginner",title:"Flow Part 6: Build Flows with the AI Flow Builder Agent",desc:"Describe what you want and watch Flow Builder place nodes."},
  {badge:"Part 7",meta:"Flow · All Levels",title:"Flow Part 7: Every Node Explained (Full Node Reference)",desc:"Tour of every remaining node in the toolbox."}
];

export const changelog=[
  {version:"v6.8.3",date:"Latest",title:"Maintenance and workflow polish",items:["Flow canvas fixes","Image Studio model list updates","Texture AI 2.0 beta access path"]},
  {version:"v6.8.0",date:"2026",title:"Flow & Video Studio expansion",items:["Node canvas improvements","Video Studio model roster","Dashboard Shared tab"]},
  {version:"v6.7",date:"2026",title:"Image Studio pipeline",items:["More generate/edit models","Style reference tools","Toolbox utilities"]}
];

export const platformFaqs=[
  {q:"How do I authenticate with the API?",a:"Create an API key from the dashboard, then include it in your requests as a Bearer token in the Authorization header."},
  {q:"What's the pricing model?",a:"Pay-as-you-go credits. No subscriptions or monthly fees. Each API call costs a set number of credits."},
  {q:"What are the rate limits?",a:"The default rate limit is 3 requests per minute per API key."},
  {q:"How do I handle errors?",a:"All errors return JSON with error message and error_code (e.g. insufficient_credits 402, rate_limit)."},
  {q:"What output formats does the API return?",a:"3D generation endpoints return GLB models. Image endpoints return PNG, JPEG, or WebP."},
  {q:"How long does 3D generation take?",a:"Most models generate in 20-60 seconds. High-quality generations can take 2-4 minutes."},
  {q:"Can I use generated models commercially?",a:"Yes. Models and images generated through the API are yours to use commercially."}
];

export const videoModels=[
  {name:"Veo 3.1 Fast",meta:"New · Excellent · ~30s · Audio · 145 cr"},
  {name:"Veo 3 Fast (Image to Video)",meta:"Animate images into clips"},
  {name:"Veo 3 Fast (Text to Video)",meta:"Generate video from text"},
  {name:"Kling (Image to Video)",meta:"Prompt-controlled motion"},
  {name:"Seedance 1.5 Pro",meta:"Flexible premium video generation"},
  {name:"Kling O1 (Frame Transition)",meta:"Frame-to-frame motion control"}
];