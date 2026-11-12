"""Independent steady continuum reference for the declared hybrid TTC stack.

Neumann lateral walls, insulated bottom, uniform dynamic bath at steady state.
Cosine modes separate x/y; through-thickness conduction is analytic, including
uniform volumetric generation in the finite active layer. No fitted constants.
"""

import numpy as np


def impedance(q, active_m, bulk_m, pad_m, silicon_k, pad_k):
    """Sensor at active-layer mid-depth; response to modal areal power W/m²."""
    q=np.asarray(q,dtype=float)
    if np.any(q<0) or not np.all(np.isfinite(q)) or min(active_m,bulk_m,pad_m,silicon_k,pad_k)<=0:
        raise ValueError('positive finite physical stack required')
    result=np.empty_like(q)
    zero=q==0
    # Uniform heating: insulated active bottom gives a quadratic temperature.
    result[zero]=3*active_m/(8*silicon_k)+bulk_m/silicon_k+pad_m/pad_k
    v=q[~zero]
    pad_y=pad_k*v/np.tanh(v*pad_m)
    t=np.tanh(v*bulk_m)
    bulk_y=silicon_k*v*(pad_y+silicon_k*v*t)/(silicon_k*v+pad_y*t)
    a=v*active_m
    result[~zero]=(1-np.cosh(a/2)/(np.cosh(a)+silicon_k*v/bulk_y*np.sinh(a)))/(silicon_k*active_m*v*v)
    return result


def transfer(geometry,group,ga,max_mode):
    if group not in ('heatsink','heatsink_with_fan') or max_mode<1 or int(max_mode)!=max_mode or not np.isfinite(ga) or ga<=0:
        raise ValueError('invalid spectral reference configuration')
    length=geometry['die_side_um']*1e-6
    # Include both zero modes. Alpha=2 for nonzero cosines, 1 for zero.
    ix,iy=np.meshgrid(np.arange(max_mode+1),np.arange(max_mode+1),indexing='xy')
    ix,iy=ix.ravel(),iy.ravel()
    q=np.pi/length*np.hypot(ix,iy)
    material=geometry['materials']['natural' if group=='heatsink' else 'fan']
    zi=impedance(q,geometry['active_silicon_um']*1e-6,geometry['bulk_silicon_um']*1e-6,
                 geometry['thermal_pad_um']*1e-6,material['SILICON']['conductivity_w_per_m_k'],
                 material['SILICONE']['conductivity_w_per_m_k'])
    source=np.zeros((len(q),16))
    alpha=np.where(ix==0,1.,2.)*np.where(iy==0,1.,2.)/length**2
    for h in geometry['heaters']:
        width,height=h['width_um']*1e-6,h['height_um']*1e-6
        cx,cy=h['x_um']*1e-6+width/2,h['y_um']*1e-6+height/2
        average=np.sinc(ix*width/(2*length))*np.cos(ix*np.pi*cx/length)
        average*=np.sinc(iy*height/(2*length))*np.cos(iy*np.pi*cy/length)
        source[:,h['power_index']]+=h['power_fraction']*alpha*average
    sensor=np.array(geometry['sensors_xy_um'])*1e-6
    observation=np.cos(ix[:,None]*np.pi*sensor[None,:,0]/length)*np.cos(iy[:,None]*np.pi*sensor[None,:,1]/length)
    resistance=observation.T @ (zi[:,None]*source)
    # The uniform dynamic bath tends to total-power / Ga at steady state.
    resistance+=1/ga
    return resistance
