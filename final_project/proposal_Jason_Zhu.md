---
title: "CSE272 Final Project Proposal"
author: Jason Zhu
geometry: margin=1in
fontfamily: libertinus
fontsize: 11pt
header-includes:
  - \usepackage{graphicx}
---

## Jason Zhu's CSE272 Final Project Proposal

**Project Selection**: Non-photorealistic rendering (Research direction) + 
Diﬀerentiable stylized rendering (more ambitious if time allows)

**Core idea**: From Post-Processing to Differentiable Stylized Path Tracing for Non-Photorealistic Rendering

### Phase 1: 2D Post-Processing Baseline (Target: finsih before 3/9 Checkpoint)
The first phase will focus on implementing standard 2D post-processing techniques on physically-based renders to establish a visual and computational baseline.

Styles to be explored include 1-bit dithering (inspired by Return of the Obra Dinn), painterly rendering, neural style transfer, and toon shading (mentioned in CSE167 lectures as reference).


### Phase 2: Stylized Path Tracing Exploration
Following the checkpoint, the project will transition from screen-space approximations to in-pipeline stylization.

The core task is to understand and replicate [West's](https://dl.acm.org/doi/epdf/10.1145/3658161) stylized path tracing algorithm.

The successful 2D post-processing methodologies from Phase 1 will be adapted into this recursive path-tracing pipeline, evaluating stylization as a function of expectation at each light bounce.

### Phase 3: Differentiable Stylized Rendering (Research Core)
The final phase tackles the ambitious research component: making the pipeline from Phase 2 differentiable.

This phase will investigate the computational challenges of computing the derivatives  for the recursive, nonlinear expectation functions used in West's algorithm.

One tangible direction I'm interested about is replicated the style of [Skypop Collective's works](https://www.sokpop.co/). I found this style visually simple but yet very appealing 

![Skypop example 1](image1.png "{width=45%}")

![Skypop example 2](image2.png "{width=45%}")

![Skypop example 3](image3.png "{width=45%}")

### Timeline:
- Complete Phase 1 before 3/9 checkpoint, and at least complete Phase 2 by the end of the class. If possible, I really want to address Phase 3 even if it's just a preliminary exploration or continue on it after the class.

### References:
- [West's Stylized Path Tracing](https://dl.acm.org/doi/epdf/10.1145/3658161)
- [Skypop Collective's website](https://www.sokpop.co/)