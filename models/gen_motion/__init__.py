"""Motion generation and rigging model wrappers.

The local-weight backends (`MoMaskModel`, `PuppeteerModel`) were removed. The
cloud rigging backends all live in `tripo_rigging_model` and are imported
directly from that module:

    from models.gen_motion.tripo_rigging_model import TripoRiggingModel
"""