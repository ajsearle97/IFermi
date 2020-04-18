"""
This module contains the classes and methods for creating iso-surface structures
from Pymatgen bandstrucutre objects. The iso-surfaces are found using the
Scikit-image package.
"""

import itertools
import warnings
from copy import deepcopy
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
from monty.json import MSONable
from skimage.measure import marching_cubes_lewiner
from trimesh import Trimesh
from trimesh.intersections import mesh_multiplane, slice_faces_plane

from ifermi.brillouin_zone import ReciprocalCell, ReciprocalSlice, WignerSeitzCell
from pymatgen import Spin, Structure
from pymatgen.electronic_structure.bandstructure import BandStructure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


@dataclass
class FermiSlice(MSONable):
    """
    A 2D slice through a Fermi surface.

    Args:
        slices: The slices for each spin channel. Given as a dictionary of
            ``{spin: spin_slices}`` where spin_slices is a List of numpy arrays, each
            with the shape ``(n_lines, 2, 2)``.
        reciprocal_slice: The reciprocal slice defining the intersection of the
            plane with the Brillouin zone edges.
        structure: The structure.

    """

    slices: Dict[Spin, List[np.ndarray]]
    reciprocal_slice: ReciprocalSlice
    structure: Structure

    @classmethod
    def from_dict(cls, d) -> "FermiSlice":
        """Returns FermiSurface object from dict."""
        fs = super().from_dict(d)
        fs.slices = {Spin(int(k)): v for k, v in fs.slices.items()}
        return fs

    def as_dict(self) -> dict:
        """Get a json-serializable dict representation of FermiSurface."""
        d = super().as_dict()
        d["slices"] = {str(spin): iso for spin, iso in self.slices.items()}
        return d


@dataclass
class FermiSurface(MSONable):
    """An object containing Fermi Surface data.

    Only stores information at k-points where energy(k) == Fermi energy.

    Args:
        isosurfaces: A dictionary containing a list of isosurfaces as ``(vertices,
            faces)`` for each spin channel.
        reciprocal_space: The reciprocal space associated with the Fermi surface.
        structure: The structure.

    """

    isosurfaces: Dict[Spin, List[Tuple[np.ndarray, np.ndarray]]]
    reciprocal_space: ReciprocalCell
    structure: Structure

    @property
    def n_surfaces(self) -> int:
        return len(self.isosurfaces)

    @classmethod
    def from_band_structure(
        cls,
        band_structure: BandStructure,
        kpoint_dim: np.ndarray,
        mu: float = 0.0,
        wigner_seitz: bool = False,
        force_primitive: bool = False,
        symprec: float = 0.001,
    ) -> "FermiSurface":
        """
        Args:
            band_structure: A band structure. The k-points must cover the full
                Brillouin zone (i.e., not just be the irreducible mesh). Use
                the ``ifermi.interpolator.Interpolator`` class to expand the k-points to
                the full Brillouin zone if required.
            kpoint_dim: The dimension of the grid in reciprocal space on which the
                energy eigenvalues are defined.
            mu: Energy offset from the Fermi energy at which the iso-surface is
               shape of the resulting iso-surface.
            wigner_seitz: Controls whether the cell is the Wigner-Seitz cell
                or the reciprocal unit cell parallelepiped.
            force_primitive: Forces the Wigner-Seitz cell to be calculated using the
            primitive lattice vector.
            symprec: Symmetry precision for determining whether the structure is the
                standard primitive unit cell.

        """
        if np.product(kpoint_dim) != len(band_structure.kpoints):
            raise ValueError(
                "Number of k-points ({}) in band structure does not match number of "
                "k-points expected from mesh dimensions ({})".format(
                    len(band_structure.kpoints), np.product(kpoint_dim)
                )
            )

        band_structure = deepcopy(band_structure)  # prevent data getting overwritten

        structure = band_structure.structure
        fermi_level = band_structure.efermi + mu
        bands = band_structure.bands
        frac_kpoints = [k.frac_coords for k in band_structure.kpoints]
        frac_kpoints = np.array(frac_kpoints)

        if wigner_seitz:
            prim = get_prim_structure(structure, symprec=symprec)
            if not np.allclose(prim.lattice.matrix, structure.lattice.matrix, 1e-5):
                warnings.warn("Structure does not match expected primitive cell")

            if force_primitive:
                warnings.warn("Using the primitive cell may give incorrect results. \n Check that the output "
                              "behaves as expected, or rerun the DFT calculation using the primitive cell "
                              "in the POSCAR file.")

            if force_primitive:
                reciprocal_space = WignerSeitzCell.from_structure(prim)
                kpoint_rlat = ReciprocalCell.from_structure(structure).reciprocal_lattice
            else:
                reciprocal_space = WignerSeitzCell.from_structure(structure)
                kpoint_rlat = None

            bands, frac_kpoints, kpoint_dim = _expand_bands(
                bands, frac_kpoints, kpoint_dim
            )

        else:
            reciprocal_space = ReciprocalCell.from_structure(structure)

        kpoint_dim = tuple(kpoint_dim.astype(int))
        isosurfaces = compute_isosurfaces(
            bands, kpoint_dim, fermi_level, reciprocal_space, force_primitive, kpoint_rlat
        )

        return cls(isosurfaces, reciprocal_space, structure)

    def get_fermi_slice(
        self, plane_normal: Tuple[int, int, int], distance: float = 0
    ) -> FermiSlice:
        """
        Get a slice through the Fermi surface, defined by the intersection of a plane
        with the fermi surface.

        Args:
            plane_normal: The plane normal in fractional indices. E.g., ``(1, 0, 0)``.
            distance: The distance from the center of the Brillouin zone (the Gamma
                point).

        Returns:
            The Fermi slice.

        """
        cart_normal = np.dot(plane_normal, self.reciprocal_space.reciprocal_lattice)
        cart_origin = cart_normal * distance

        slices = {}
        for spin, spin_isosurfaces in self.isosurfaces.items():
            spin_slices = []

            for verts, faces in spin_isosurfaces:
                mesh = Trimesh(vertices=verts, faces=faces)
                lines = mesh_multiplane(mesh, cart_origin, cart_normal, [0])[0][0]
                spin_slices.append(lines)

            slices[spin] = spin_slices

        reciprocal_slice = self.reciprocal_space.get_reciprocal_slice(
            plane_normal, distance
        )

        return FermiSlice(slices, reciprocal_slice, self.structure)

    @classmethod
    def from_dict(cls, d) -> "FermiSurface":
        """Returns FermiSurface object from dict."""
        fs = super().from_dict(d)
        fs.isosurfaces = {Spin(int(k)): v for k, v in fs.isosurfaces.items()}
        return fs

    def as_dict(self) -> dict:
        """Get a json-serializable dict representation of FermiSurface."""
        d = super().as_dict()
        d["isosurfaces"] = {str(spin): iso for spin, iso in self.isosurfaces.items()}
        return d


def compute_isosurfaces(
    bands: Dict[Spin, np.ndarray],
    kpoint_dim: Tuple[int, int, int],
    fermi_level: float,
    reciprocal_space: ReciprocalCell,
    force_primitive: bool = False,
    kpoint_rlat: np.array = None
) -> Dict[Spin, List[Tuple[np.ndarray, np.ndarray]]]:
    """
    Compute the isosurfaces at a particular energy level.

    Args:
        bands: The band energies, given as a dictionary of ``{spin: energies}``, where
            energies has the shape (nbands, nkpoints).
        kpoint_dim: The k-point mesh dimensions.
        fermi_level: The energy at which to calculate the Fermi surface.
        reciprocal_space: The reciprocal space representation.

    Returns:
        A dictionary containing a list of isosurfaces as ``(vertices, faces)`` for
        each spin channel.
    """
    if force_primitive:
        rlat = kpoint_rlat

    else:
        rlat = reciprocal_space.reciprocal_lattice

    spacing = 1 / (np.array(kpoint_dim) - 1)

    isosurfaces = {}
    for spin, ebands in bands.items():
        ebands -= fermi_level
        spin_isosurface = []

        for band in ebands:
            # check if band crosses fermi level
            if np.nanmax(band) > 0 > np.nanmin(band):
                band_data = band.reshape(kpoint_dim)
                verts, faces, _, _ = marching_cubes_lewiner(band_data, 0, spacing)

                if isinstance(reciprocal_space, WignerSeitzCell):
                    verts = np.dot(verts - 0.5, rlat) * 3
                    verts, faces = _trim_surface(reciprocal_space, verts, faces)
                else:
                    # convert coords to cartesian
                    verts = np.dot(verts - 0.5, rlat)

                spin_isosurface.append((verts, faces))

        isosurfaces[spin] = spin_isosurface

    return isosurfaces


def _trim_surface(
    wigner_seitz_cell: WignerSeitzCell, vertices: np.ndarray, faces: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Trim the surface to remove parts outside the cell boundaries.

    Will add new triangles at the boundary edges as necessary to produce a smooth
    surface.

    Args:
        wigner_seitz_cell: The reciprocal space object.
        vertices: The surface vertices.
        faces: The surface faces.

    Returns:
        The trimmed surface as a tuple of ``(vertices, faces)``.
    """
    for center, normal in zip(wigner_seitz_cell.centers, wigner_seitz_cell.normals):
        vertices, faces = slice_faces_plane(vertices, faces, -normal, center)
    return vertices, faces


def _expand_bands(
    bands: Dict[Spin, np.ndarray], frac_kpoints: np.ndarray, kpoint_dim: np.ndarray
) -> Tuple[Dict[Spin, np.ndarray], np.ndarray, np.ndarray]:
    """
    Expand the band energies and k-points with periodic boundary conditions to form a
    3x3x3 supercell.

    Args:
        bands: The band energies, given as a dictionary of ``{spin: energies}``, where
            energies has the shape (nbands, nkpoints).
        frac_kpoints: The fractional k-point coordinates.
        kpoint_dim: The k-point mesh dimensions.

    Returns:
        The expanded band energies, k-points, and k-point mesh dimensions.
    """
    final_ebands = {}
    for spin, ebands in bands.items():
        super_ebands = []
        images = (-1, 0, 1)

        super_kpoints = np.array([], dtype=np.int64).reshape(0, 3)
        for i, j, k in itertools.product(images, images, images):
            k_image = frac_kpoints + [i, j, k]
            super_kpoints = np.concatenate((super_kpoints, k_image), axis=0)

        sort_idx = np.lexsort(
            (super_kpoints[:, 2], super_kpoints[:, 1], super_kpoints[:, 0])
        )
        final_kpoints = super_kpoints[sort_idx]

        for band in ebands:
            super_band = np.array([], dtype=np.int64)
            for _ in range(27):
                super_band = np.concatenate((super_band, band), axis=0)
            super_ebands.append(super_band[sort_idx])

        final_ebands[spin] = np.array(super_ebands)

    return final_ebands, final_kpoints, kpoint_dim * 3


def get_prim_structure(structure, symprec=0.01) -> Structure:
    """
    Get the primitive structure.

    Args:
        structure: The structure.
        symprec: The symmetry precision in Angstrom.

    Returns:
       The primitive cell as a pymatgen Structure object.
    """
    analyzer = SpacegroupAnalyzer(structure, symprec=symprec)
    return analyzer.get_primitive_standard_structure()
