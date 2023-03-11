# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
#
# Copyright 2021 The NiPreps Developers <nipreps@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# We support and encourage derived works from this project, please read
# about our expectations at
#
#     https://www.nipreps.org/community/licensing/
#
"""Writing out functional reportlets."""
from mriqc import config
from mriqc.interfaces import DerivativesDataSink

from nipype.pipeline import engine as pe
from nipype.interfaces import utility as niu


def init_func_report_wf(name="func_report_wf"):
    """
    Write out individual reportlets.

    .. workflow::

        from mriqc.workflows.functional.output import init_func_report_wf
        from mriqc.testing import mock_config
        with mock_config():
            wf = init_func_report_wf()

    """
    from niworkflows.interfaces.plotting import FMRISummary
    from niworkflows.interfaces.morphology import BinaryDilation, BinarySubtraction

    from nireports.interfaces import PlotMosaic, PlotSpikes
    from mriqc.interfaces.functional import Spikes
    # from mriqc.interfaces.reports import IndividualReport

    verbose = config.execution.verbose_reports
    mem_gb = config.workflow.biggest_file_gb
    reportlets_dir = config.execution.output_dir

    workflow = pe.Workflow(name=name)
    inputnode = pe.Node(
        niu.IdentityInterface(
            fields=[
                "in_ras",
                "hmc_epi",
                "epi_mean",
                "brainmask",
                "hmc_fd",
                "fd_thres",
                "epi_parc",
                "in_dvars",
                "in_stddev",
                "outliers",
                "in_spikes",
                "in_fft",
                "in_iqms",
                "mni_report",
                "ica_report",
                "meta_sidecar",
                "name_source",
            ]
        ),
        name="inputnode",
    )

    # Set FD threshold
    inputnode.inputs.fd_thres = config.workflow.fd_thres

    spmask = pe.Node(
        niu.Function(
            input_names=["in_file", "in_mask"],
            output_names=["out_file", "out_plot"],
            function=spikes_mask,
        ),
        name="SpikesMask",
        mem_gb=mem_gb * 3.5,
    )

    spikes_bg = pe.Node(
        Spikes(no_zscore=True, detrend=False),
        name="SpikesFinderBgMask",
        mem_gb=mem_gb * 2.5,
    )

    # Generate crown mask
    # Create the crown mask
    dilated_mask = pe.Node(BinaryDilation(), name="dilated_mask")
    subtract_mask = pe.Node(BinarySubtraction(), name="subtract_mask")
    parcels = pe.Node(niu.Function(function=_carpet_parcellation), name="parcels")

    bigplot = pe.Node(FMRISummary(), name="BigPlot", mem_gb=mem_gb * 3.5)

    # fmt: off
    workflow.connect([
        (inputnode, spikes_bg, [("in_ras", "in_file")]),
        (inputnode, spmask, [("in_ras", "in_file")]),
        (inputnode, bigplot, [("hmc_epi", "in_func"),
                              ("hmc_fd", "fd"),
                              ("fd_thres", "fd_thres"),
                              ("in_dvars", "dvars"),
                              ("outliers", "outliers"),
                              (("meta_sidecar", _get_tr), "tr")]),
        (inputnode, parcels, [("epi_parc", "segmentation")]),
        (inputnode, dilated_mask, [("brainmask", "in_mask")]),
        (inputnode, subtract_mask, [("brainmask", "in_subtract")]),
        (dilated_mask, subtract_mask, [("out_mask", "in_base")]),
        (subtract_mask, parcels, [("out_mask", "crown_mask")]),
        (parcels, bigplot, [("out", "in_segm")]),
        (spikes_bg, bigplot, [("out_tsz", "in_spikes_bg")]),
        (spmask, spikes_bg, [("out_file", "in_mask")]),
    ])
    # fmt: on

    mosaic_mean = pe.Node(
        PlotMosaic(
            out_file="plot_func_mean_mosaic1.svg",
            cmap="Greys_r",
        ),
        name="PlotMosaicMean",
    )

    mosaic_stddev = pe.Node(
        PlotMosaic(
            out_file="plot_func_stddev_mosaic2_stddev.svg",
            cmap="viridis",
        ),
        name="PlotMosaicSD",
    )

    ds_report_mean = pe.Node(
        DerivativesDataSink(
            base_directory=reportlets_dir,
            desc="mean",
            datatype="figures",
        ),
        name="ds_report_mean",
        run_without_submitting=True,
    )

    ds_report_stdev = pe.Node(
        DerivativesDataSink(
            base_directory=reportlets_dir,
            desc="stdev",
            datatype="figures",
        ),
        name="ds_report_stdev",
        run_without_submitting=True,
    )

    ds_report_carpet = pe.Node(
        DerivativesDataSink(
            base_directory=reportlets_dir,
            desc="carpet",
            datatype="figures",
        ),
        name="ds_report_carpet",
        run_without_submitting=True,
    )

    # fmt: off
    workflow.connect([
        # (inputnode, rnode, [("in_iqms", "in_iqms")]),
        (inputnode, mosaic_mean, [("epi_mean", "in_file")]),
        (inputnode, mosaic_stddev, [("in_stddev", "in_file")]),
        (inputnode, ds_report_mean, [("name_source", "source_file")]),
        (inputnode, ds_report_stdev, [("name_source", "source_file")]),
        (inputnode, ds_report_carpet, [("name_source", "source_file")]),
        (mosaic_mean, ds_report_mean, [("out_file", "in_file")]),
        (mosaic_stddev, ds_report_stdev, [("out_file", "in_file")]),
        (bigplot, ds_report_carpet, [("out_file", "in_file")]),
    ])
    # fmt: on

    if config.workflow.fft_spikes_detector:
        mosaic_spikes = pe.Node(
            PlotSpikes(
                out_file="plot_spikes.svg",
                cmap="viridis",
                title="High-Frequency spikes",
            ),
            name="PlotSpikes",
        )

        ds_report_spikes = pe.Node(
            DerivativesDataSink(
                base_directory=reportlets_dir,
                desc="spikes",
                datatype="figures",
            ),
            name="ds_report_spikes",
            run_without_submitting=True,
        )

        # fmt: off
        workflow.connect([
            (inputnode, ds_report_spikes, [("name_source", "source_file")]),
            (inputnode, mosaic_spikes, [("in_ras", "in_file"),
                                        ("in_spikes", "in_spikes"),
                                        ("in_fft", "in_fft")]),
            (mosaic_spikes, ds_report_spikes, [("out_file", "in_file")]),
        ])
        # fmt: on

    if config.workflow.ica:
        ds_report_ica = pe.Node(
            DerivativesDataSink(
                base_directory=reportlets_dir,
                desc="ica",
                datatype="figures",
            ),
            name="ds_report_ica",
            run_without_submitting=True,
        )
        # fmt: off
        workflow.connect([
            (inputnode, ds_report_ica, [("name_source", "source_file"),
                                        ("ica_report", "in_file")]),
        ])
        # fmt: on

    if not verbose:
        return workflow

    # Verbose-reporting goes here
    from nireports.interfaces import PlotContours

    mosaic_zoom = pe.Node(
        PlotMosaic(
            cmap="Greys_r",
        ),
        name="PlotMosaicZoomed",
    )

    mosaic_noise = pe.Node(
        PlotMosaic(
            only_noise=True,
            cmap="viridis_r",
        ),
        name="PlotMosaicNoise",
    )

    if config.workflow.species.lower() in ("rat", "mouse"):
        mosaic_mean.inputs.view = ("coronal", "axial")
        mosaic_stddev.inputs.view = ("coronal", "axial")
        mosaic_zoom.inputs.view = ("coronal", "axial")
        mosaic_noise.inputs.view = ("coronal", "axial")

    plot_bmask = pe.Node(
        PlotContours(
            display_mode="y" if config.workflow.species.lower() in ("rat", "mouse") else "z",
            levels=[0.5],
            colors=["r"],
            cut_coords=10,
            out_file="bmask",
        ),
        name="PlotBrainmask",
    )

    ds_report_zoomed = pe.Node(
        DerivativesDataSink(
            base_directory=reportlets_dir,
            desc="zoomed",
            datatype="figures",
        ),
        name="ds_report_zoomed",
        run_without_submitting=True,
    )

    ds_report_background = pe.Node(
        DerivativesDataSink(
            base_directory=reportlets_dir,
            desc="background",
            datatype="figures",
        ),
        name="ds_report_background",
        run_without_submitting=True,
    )

    ds_report_bmask = pe.Node(
        DerivativesDataSink(
            base_directory=reportlets_dir,
            desc="brainmask",
            datatype="figures",
        ),
        name="ds_report_bmask",
        run_without_submitting=True,
    )

    ds_report_norm = pe.Node(
        DerivativesDataSink(
            base_directory=reportlets_dir,
            desc="norm",
            datatype="figures",
        ),
        name="ds_report_norm",
        run_without_submitting=True,
    )

    # fmt: off
    workflow.connect([
        (inputnode, ds_report_norm, [("mni_report", "in_file"),
                                     ("name_source", "source_file")]),
        (inputnode, plot_bmask, [("epi_mean", "in_file"),
                                 ("brainmask", "in_contours")]),
        (inputnode, mosaic_zoom, [("epi_mean", "in_file"),
                                  ("brainmask", "bbox_mask_file")]),
        (inputnode, mosaic_noise, [("epi_mean", "in_file")]),
        (inputnode, ds_report_zoomed, [("name_source", "source_file")]),
        (inputnode, ds_report_background, [("name_source", "source_file")]),
        (inputnode, ds_report_bmask, [("name_source", "source_file")]),
        (mosaic_zoom, ds_report_zoomed, [("out_file", "in_file")]),
        (mosaic_noise, ds_report_background, [("out_file", "in_file")]),
        (plot_bmask, ds_report_bmask, [("out_file", "in_file")]),
    ])
    # fmt: on

    return workflow


def spikes_mask(in_file, in_mask=None, out_file=None):
    """Calculate a mask in which check for :abbr:`EM (electromagnetic)` spikes."""
    import os.path as op

    import nibabel as nb
    import numpy as np
    from nilearn.image import mean_img
    from nilearn.plotting import plot_roi
    from scipy import ndimage as nd

    if out_file is None:
        fname, ext = op.splitext(op.basename(in_file))
        if ext == ".gz":
            fname, ext2 = op.splitext(fname)
            ext = ext2 + ext
        out_file = op.abspath("{}_spmask{}".format(fname, ext))
        out_plot = op.abspath("{}_spmask.pdf".format(fname))

    in_4d_nii = nb.load(in_file)
    orientation = nb.aff2axcodes(in_4d_nii.affine)

    if in_mask:
        mask_data = np.asanyarray(nb.load(in_mask).dataobj)
        a = np.where(mask_data != 0)
        bbox = (
            np.max(a[0]) - np.min(a[0]),
            np.max(a[1]) - np.min(a[1]),
            np.max(a[2]) - np.min(a[2]),
        )
        longest_axis = np.argmax(bbox)

        # Input here is a binarized and intersected mask data from previous section
        dil_mask = nd.binary_dilation(
            mask_data, iterations=int(mask_data.shape[longest_axis] / 9)
        )

        rep = list(mask_data.shape)
        rep[longest_axis] = -1
        new_mask_2d = dil_mask.max(axis=longest_axis).reshape(rep)

        rep = [1, 1, 1]
        rep[longest_axis] = mask_data.shape[longest_axis]
        new_mask_3d = np.logical_not(np.tile(new_mask_2d, rep))
    else:
        new_mask_3d = np.zeros(in_4d_nii.shape[:3]) == 1

    if orientation[0] in ["L", "R"]:
        new_mask_3d[0:2, :, :] = True
        new_mask_3d[-3:-1, :, :] = True
    else:
        new_mask_3d[:, 0:2, :] = True
        new_mask_3d[:, -3:-1, :] = True

    mask_nii = nb.Nifti1Image(
        new_mask_3d.astype(np.uint8), in_4d_nii.affine, in_4d_nii.header
    )
    mask_nii.to_filename(out_file)

    plot_roi(mask_nii, mean_img(in_4d_nii), output_file=out_plot)
    return out_file, out_plot


def _carpet_parcellation(segmentation, crown_mask):
    """Generate the union of two masks."""
    from pathlib import Path
    import numpy as np
    import nibabel as nb

    img = nb.load(segmentation)

    lut = np.zeros((256,), dtype="uint8")
    lut[100:201] = 1  # Ctx GM
    lut[30:99] = 2  # dGM
    lut[1:11] = 3  # WM+CSF
    lut[255] = 4  # Cerebellum
    # Apply lookup table
    seg = lut[np.asanyarray(img.dataobj, dtype="uint16")]
    seg[np.asanyarray(nb.load(crown_mask).dataobj, dtype=int) > 0] = 5

    outimg = img.__class__(seg.astype("uint8"), img.affine, img.header)
    outimg.set_data_dtype("uint8")
    out_file = Path("segments.nii.gz").absolute()
    outimg.to_filename(out_file)
    return str(out_file)


def _get_tr(meta_dict):
    return meta_dict.get("RepetitionTime", None)
