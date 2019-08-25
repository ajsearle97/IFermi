"""
    This module implements a plotter for the Fermi-Surface of a material
    todo:
    * Remap into Brillioun zone (Wigner Seitz cell)
    * Get Latex working for labels
    * Do projections onto arbitrary surface
    * Comment more
    * Think about classes/methods, maybe restructure depending on sumo layout
    
    """


import numpy as np
import sympy

# plotting library imports
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from mpl_toolkits.mplot3d.art3d import Line3DCollection
from matplotlib import colors as mcolors
from matplotlib import rc
from matplotlib.ticker import MultipleLocator
import colorlover as cl
import itertools

import plotly
import plotly.graph_objs as go
from plotly.offline import download_plotlyjs, init_notebook_mode, plot, iplot

from BoltzTraP2.units import *
from BoltzTraP2.fite import *
from BoltzTraP2.dft import *

from bulk_objects import FermiSurface, RecipCell

from pymatgen.io.vasp.outputs import Vasprun
from pymatgen.electronic_structure.core import Spin
from pymatgen.symmetry.bandstructure import *

class FSPlotter(object):

    """Class containing functions for plotting the Fermi Surface of band structure objects.
    """
    
    def __init__(self, fs: FermiSurface, rc: RecipCell):
        """
        Args:
            fermi_surface (FermiSurface): A FermiSurface object to be used in plotting
            bz_corners (np.array[np.array]): A list of numpy arrays of the corners of the facets of the Brillioun zone. 
        """
        if not isinstance(fs, FermiSurface):
            raise ValueError(
                "FSPlotter only works with FermiSurface objects. "
                "A bandstructure must first be converted to a FermiSurface object.")
        self._fermi_surface = fs
        self._recip_cell = rc

        self._symmetry_pts = self._add_symmetry_points(fs)

    def _add_symmetry_points(self, fs):

        kpts, labels = [], []

        first, second = HighSymmKpath(fs._structure).get_kpoints(coords_are_cartesian=False)


        for i, j in zip(first, second):
            if not len(j)==0:
                kpts.append(i)
                labels.append(j)

        return kpts, labels

    
    def fs_plot_data(self, plot_type = 'mpl', bz_linewidth= 0.9, axis_labels = True, symmetry_labels = True, color_list = None, title_str = None):
        """Function for producing a plot of the Fermi surface.
        Will edit this to allow for custom plotting options.
        """

        meshes = []

        if plot_type == 'mpl':

            fig = plt.figure(figsize=(10, 10))
            ax = fig.add_subplot(111, projection='3d')

            rlattvec =  self._brillouin_zone._rlattvec
        
            # specify the colour list for plotting the bands. 
            # Below is the deafult, can be overidden by specifying 'colour' in calling function.
            if color_list is None:
                color_list = plt.cm.Set1(np.linspace(0, 1, 9))

            # create a mesh for each electron band which has an isosurface at the Fermi energy.
            # mesh data is generated by a marching cubes algorithm when the FermiSurface object is created.
            for i, band in enumerate(self._fermi_surface._iso_surface,  0):
                
                verts = band[0]
                faces = band[1]

                grid = [np.array([item[0] for item in verts]), np.array([item[1] for item in verts]), np.array([item[2] for item in verts])]
                
                # reposition the vertices so that the cente of the Brill Zone is at (0,0,0)
                # include if want gamma at centre of plot, along with "rearrange_data method in bulk_objects"
                # verts -= np.array([grid[0].max()/2,grid[1].max()/2,grid[2].max()/2])

                # create a mesh and add it to the plot
                mesh = Poly3DCollection(verts[faces], linewidths=0.1)
                mesh.set_facecolor(color_list[i])
                mesh.set_edgecolor('lightgray')
                ax.add_collection3d(mesh)

            # add the Brillouin Zone outline to the plot
            corners = self._recip_cell._faces

            ax.add_collection3d(Line3DCollection(corners, colors='k', linewidths=bz_linewidth))

            # add high-symmetry points to the plot

            sym_pts = self._symmetry_pts

            x, y, z = zip(*sym_pts[0])

            # Placeholders for the high-symmetry points in cartesian coordinates
            x_cart, y_cart, z_cart = [], [], []

            # Convert high-symmetry point coordinates into cartesian, and shift to match mesh position
            for i in x:
                if i < 0:
                    i = np.linalg.norm([rlattvec[:,0]])*((0.5+i)+0.5)
                else:
                    i = np.linalg.norm(rlattvec[:,0])*(i)
                x_cart.append(i)

            for i in y:
                if i < 0:
                    i = np.linalg.norm(rlattvec[:,1])*((0.5+i)+0.5)
                else:
                    i = np.linalg.norm(rlattvec[:,1])*(i)
                y_cart.append(i)

            for i in z:
                if i < 0:
                    i = np.linalg.norm(rlattvec[:,2])*((0.5+i)+0.5)
                else:
                    i = np.linalg.norm(rlattvec[:,2])*(i)
                z_cart.append(i)

            ax.scatter(x_cart, y_cart, z_cart, s=10, c='k')

            for i, txt in enumerate(sym_pts[1]):
                ax.text(x_cart[i],y_cart[i],z_cart[i],  '%s' % (txt), size=15, zorder=1, color='k')

            ax.axis('off')
        
            if title_str is not None:
                plt.title(title_str)
        
            ax.set_xlim(0, np.linalg.norm(rlattvec[:,0])+1)
            ax.set_ylim(0, np.linalg.norm(rlattvec[:,1])+1)
            ax.set_zlim(0, np.linalg.norm(rlattvec[:,2])+1)
        
            plt.tight_layout()
            plt.show()

        elif plot_type == 'plotly':

            init_notebook_mode(connected=True)

            # plotly.tools.set_credentials_file(username='asearle', api_key='PiOwBRIRWKGJWIFXe1vT')

            rlattvec = self._recip_cell._rlattvec

            # Different colours
        
            # colors = [
            #             '#1f77b4',  # muted blue
            #             '#ff7f0e',  # safety orange
            #             '#2ca02c',  # cooked asparagus green
            #             '#d62728',  # brick red
            #             '#9467bd',  # muted purple
            #             '#8c564b',  # chestnut brown
            #             '#e377c2',  # raspberry yogurt pink
            #             '#7f7f7f',  # middle gray
            #             '#bcbd22',  # curry yellow-green
            #             '#17becf',   # blue-teal
            #             '#00FFFF'   #another blue teal
            #             '#1f77b4',  # muted blue
            #             '#ff7f0e',  # safety orange
            #             '#2ca02c',  # cooked asparagus green
            #             '#d62728',  # brick red
            #             '#9467bd',  # muted purple
            #             '#8c564b',  # chestnut brown
            #             '#e377c2',  # raspberry yogurt pink
            #             '#7f7f7f',  # middle gray
            #             '#bcbd22',  # curry yellow-green
            #             '#17becf',   # blue-teal
            #             '#00FFFF'   #another blue teal
            #             ]

            colors = cl.scales['11']['qual']['Set3']
        
            # create a mesh for each electron band which has an isosurface at the Fermi energy.
            # mesh data is generated by a marching cubes algorithm when the FermiSurface object is created.
            for i, band in enumerate(self._fermi_surface._iso_surface,  0):

                
                verts = band[0]
                faces = band[1]

                
                grid = [np.array([np.abs(item[0]) for item in verts]), np.array([np.abs(item[1]) for item in verts]), np.array([np.abs(item[2]) for item in verts])]
                
                x, y, z = zip(*verts)

                I, J, K = ([triplet[c] for triplet in faces] for c in range(3))

                trace = go.Mesh3d(x=x,
                         y=y,
                         z=z,
                         color=colors[i], opacity = 0.9, 
                         i=I,
                         j=J,
                         k=K)
                meshes.append(trace)

            # add the Brillouin Zone outline to the plot
            corners = self._recip_cell._faces
       
            for facet in corners:
                x, y, z = zip(*facet)
        
                trace = go.Scatter3d(x=x, y=y, z=z, mode = 'lines',
                                    line=dict(
                                    color='black',
                                    width=3
                                    ))

                meshes.append(trace)

            # add the high symmetry points to the plot
            sym_pts = self._symmetry_pts

            # Get text labels into Latex form

            labels = []

            for i in sym_pts[1]:
                labels.append(sympy.latex(i))

            x, y, z = zip(*sym_pts[0])

            # Placeholders for the high-symmetry points in cartesian coordinates
            x_cart, y_cart, z_cart = [], [], []

            # Convert high-symmetry point coordinates into cartesian, and shift to match mesh position
            for i in x:
                if i < 0:
                    i = np.linalg.norm([rlattvec[:,0]])*((0.5+i)+0.5)
                else:
                    i = np.linalg.norm(rlattvec[:,0])*(i)
                x_cart.append(i)

            for i in y:
                if i < 0:
                    i = np.linalg.norm(rlattvec[:,1])*((0.5+i)+0.5)
                else:
                    i = np.linalg.norm(rlattvec[:,1])*(i)
                y_cart.append(i)

            for i in z:
                if i < 0:
                    i = np.linalg.norm(rlattvec[:,2])*((0.5+i)+0.5)
                else:
                    i = np.linalg.norm(rlattvec[:,2])*(i)
                z_cart.append(i)

            trace = go.Scatter3d(x=x_cart, y=y_cart, z=z_cart, 
                                mode='markers+text',
                                marker = dict(size = 5,
                                color = 'black'
                                ),
                                name='Markers and Text',
                                text = labels,
                                textposition='bottom center'
                            )

            meshes.append(trace)

            # Specify plot parameters

            layout = go.Layout(scene = dict(xaxis=dict(title = '',
                                showgrid=True,
                                zeroline=True,
                                showline=False,
                                ticks='',
                                showticklabels=False), yaxis=dict(title = '',
                                showgrid=True,
                                zeroline=True,
                                showline=False,
                                ticks='',
                                showticklabels=False), 
                                zaxis=dict(title = '',
                                showgrid=True,
                                zeroline=True,
                                showline=False,
                                ticks='',
                                showticklabels=False)),
                                showlegend=False, title=go.layout.Title(
                                text=title_str,
                                xref='paper',
                                x=0
                                ))

            plot(go.Figure(data=meshes,layout= layout), include_mathjax='cdn')

        else:
            raise ValueError(
                "The type you have entered is not a valid option for the plot_type parameter."
                "Please enter one of {'mpl', 'plotly'} for a matplotlib or plotly-type plot" 
                " respectively. For an interactive plot 'plotly' is recommended.")
