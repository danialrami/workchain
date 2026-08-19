# Psychoacoustic model functions v3
# Based on psyac_utils_v2.py, incorporating feedback for better accuracy and audio quality.

import numpy as np
import librosa # Added missing import

def hz2bark(f):
    """ Converts frequencies in Hz to the Bark scale. """
    f = np.maximum(f, 1e-9) # Avoid zero or negative frequencies
    return 6. * np.arcsinh(f / 600.)

def bark2hz(Brk):
    """ Converts Bark scale values back to Hz. """
    return 600. * np.sinh(Brk / 6.)

def spreading_function_dB(bark_diff, alpha):
    """
    Calculates the spreading function value in dB for a given Bark distance.
    Based on Schroeder, Atal (1979) and Terhardt (1979) models, adapted.
    Args:
        bark_diff (float): Difference in Bark scale (masker - masked).
        alpha (float): Tonality factor (0 for noise-like, 1 for tone-like, typically 0.5-0.8).
                       Not directly used in this simplified version but kept for potential extension.
    Returns:
        float: Spreading function value in dB.
    """
    # Simplified spreading function: slopes based roughly on common models
    if bark_diff >= 0:
        # Upper slope (masking effect decreases above masker frequency)
        slope = -12 # dB per Bark
    else:
        # Lower slope (masking effect decreases more steeply below masker frequency)
        slope = -27 # dB per Bark

    # Basic model: Offset + Slope * BarkDistance
    # Offset determines the masking level at the masker frequency itself (relative to masker level)
    # Let's assume a base offset, e.g., -10dB (masking is less than masker level)
    offset = -10
    spreading_val_dB = offset + slope * abs(bark_diff)

    # Ensure a minimum masking effect (floor)
    return max(spreading_val_dB, -100.0) # Limit minimum masking effect

def spreadingfunctionmat_v3(nfilts, alpha):
    """
    Creates the spreading function matrix on the Bark scale.
    Args:
        nfilts (int): Number of Bark filters.
        alpha (float): Tonality factor (used in the calculation of amplitude conversion).
    Returns:
        np.ndarray: Spreading function matrix (nfilts x nfilts) in amplitude ratio (not dB).
                      Element [i, j] represents the masking effect of band i onto band j.
    """
    spreadingfuncmatrix_dB = np.zeros((nfilts, nfilts))
    bark_centers = np.arange(nfilts) # Assume Bark bands are indexed 0 to nfilts-1

    for i in range(nfilts): # Masker band index
        for j in range(nfilts): # Masked band index
            bark_diff = bark_centers[j] - bark_centers[i]
            spreadingfuncmatrix_dB[i, j] = spreading_function_dB(bark_diff, alpha)

    # Convert dB relative masking to amplitude ratio, incorporating alpha
    # Masking effect = Masker_Amplitude^alpha * Spreading_Function_Amplitude^alpha
    # We need Spreading_Function_Amplitude = 10^(spreading_dB / 20)
    # The matrix stores the spreading part: (10^(spreading_dB / 20))^alpha
    spreadingfuncmatrix_amp = (10.0**(spreadingfuncmatrix_dB / 20.0))**alpha
    return spreadingfuncmatrix_amp

def mapping2barkmat_v3(fs, nfilts, nfft):
    """
    Constructs mapping matrix W from linear frequency (FFT bins) to Bark scale using triangular weighting.
    Ensures energy conservation and handles edge cases.
    """
    max_freq = fs / 2.0
    n_freq_bins = nfft // 2 + 1
    maxbark = hz2bark(max_freq)
    if nfilts <= 1: return np.ones((1, n_freq_bins)) # Handle edge case

    # FFT bin frequencies
    bin_freqs = librosa.fft_frequencies(sr=fs, n_fft=nfft) # Use librosa for consistency
    # Bark values for each FFT bin
    binbark = hz2bark(bin_freqs)

    W = np.zeros((nfilts, n_freq_bins))
    # Define Bark band center frequencies
    bark_centers = np.linspace(0, maxbark, nfilts)
    # Define Bark band boundaries (midpoints between centers, plus ends)
    bark_boundaries = np.concatenate(([bark_centers[0] - (bark_centers[1]-bark_centers[0])/2],
                                     (bark_centers[:-1] + bark_centers[1:]) / 2,
                                     [bark_centers[-1] + (bark_centers[-1]-bark_centers[-2])/2]))
    bark_boundaries = np.maximum(0, bark_boundaries) # Ensure boundaries are non-negative

    for i in range(nfilts):
        lower_bark = bark_boundaries[i]
        upper_bark = bark_boundaries[i+1]
        center_bark = bark_centers[i]

        # Indices of FFT bins within the current Bark band (triangular window)
        indices = np.where((binbark >= lower_bark) & (binbark < upper_bark))[0]

        if len(indices) > 0:
            # Calculate weights using a triangular window centered at center_bark
            dist_from_center = np.abs(binbark[indices] - center_bark)
            max_dist = (upper_bark - lower_bark) / 2.0
            if max_dist > 1e-9:
                weights = 1.0 - (dist_from_center / max_dist)
                weights = np.maximum(0, weights) # Ensure non-negative weights
                W[i, indices] = weights
            elif len(indices) == 1: # Handle case where band is very narrow (single bin)
                 W[i, indices[0]] = 1.0

    # Normalize rows: Ensure that the sum of weights for each Bark band is 1.
    row_sums = np.sum(W, axis=1)
    non_zero_rows = row_sums > 1e-9
    W[non_zero_rows] /= row_sums[non_zero_rows][:, np.newaxis]

    return W

def mapping2bark_v3(mX, W):
    """ Maps magnitude spectrum vector mX from DFT to the Bark scale using matrix W. """
    nfreqs = W.shape[1]
    if len(mX) != nfreqs:
        # Pad or truncate mX if necessary
        mX_adj = np.zeros(nfreqs)
        min_len = min(len(mX), nfreqs)
        mX_adj[:min_len] = mX[:min_len]
        mX = mX_adj

    # Map powers (amplitude squared) and convert back to amplitude
    mX_power = np.abs(mX)**2.0
    mXbark_power = np.dot(W, mX_power) # W shape (nfilts, nfreqs), mX_power shape (nfreqs,)
    mXbark = np.sqrt(np.maximum(mXbark_power, 1e-18)) # Add epsilon before sqrt
    return mXbark

def mappingfrombarkmat_v3(W):
    """ Constructs inverse mapping matrix W_inv from Bark scale back to linear frequency. """
    # Use the transpose of the (normalized) mapping matrix W.
    W_inv = W.T
    # Optional: Normalize columns of W_inv to better distribute energy back
    col_sums = np.sum(W_inv, axis=0) + 1e-9
    W_inv /= col_sums[np.newaxis, :]
    return W_inv

def mappingfrombark_v3(mTbark, W_inv):
    """ Maps Bark scale masking threshold mTbark back to the linear frequency scale. """
    # Use the pseudo-inverse matrix W_inv for mapping back
    mT = np.dot(W_inv, mTbark) # W_inv shape (nfreqs, nfilts), mTbark shape (nfilts,)
    return mT

def threshold_in_quiet_dBFS(fs, nfft):
    """
    Calculates the Threshold in Quiet (LTQ) in dB relative to Full Scale (dBFS).
    Assumes 0 dBFS corresponds to an amplitude of 1.0.
    Uses a formula similar to ISO 389-7, adjusted for dBFS reference.
    """
    n_freq_bins = nfft // 2 + 1
    frequencies = librosa.fft_frequencies(sr=fs, n_fft=nfft)
    frequencies = np.maximum(frequencies, 1e-6) # Avoid zero frequency
    f_khz = frequencies / 1000.0

    # ISO 389-7 formula for threshold in dB SPL
    LTQ_dB_SPL = (3.64 * (f_khz**-0.8)
                  - 6.5 * np.exp(-0.6 * (f_khz - 3.3)**2.)
                  + (10**-3) * (f_khz**4.))

    # Convert dB SPL to dBFS. This requires an assumption about the SPL level corresponding to 0 dBFS.
    # A common reference is 96 dB SPL = 0 dBFS for 16-bit audio, or higher for floats.
    # Let's assume 100 dB SPL = 0 dBFS for float audio as a plausible reference.
    # dBFS = dB_SPL - Reference_SPL_for_0_dBFS
    ref_spl_for_0_dbfs = 100.0
    LTQ_dBFS = LTQ_dB_SPL - ref_spl_for_0_dbfs

    # Add frequency-dependent safety margin (in dB)
    safety_margin_dB = np.zeros_like(LTQ_dBFS)
    safety_margin_dB[frequencies < 1000] = 6 # More margin at low frequencies
    safety_margin_dB[frequencies >= 1000] = 3 # Less margin at high frequencies
    LTQ_dBFS += safety_margin_dB

    # Clip to a reasonable range below 0 dBFS, e.g., -120 dBFS to -10 dBFS
    LTQ_dBFS = np.clip(LTQ_dBFS, -120.0, -10.0)

    return LTQ_dBFS

def maskingThreshold_v3(mX, fs, nfft, nfilts, alpha, W, W_inv, spreadingfuncmatrix):
    """
    Computes the masking threshold on the linear frequency scale (amplitude relative to 1.0).
    Version 3: Uses dBFS for threshold in quiet and combines thresholds carefully.
    Args:
        mX (np.ndarray): Magnitude spectrum of the current frame (linear frequency scale, amplitude relative to 1.0).
        fs (int): Sample rate.
        nfft (int): FFT size.
        nfilts (int): Number of Bark filters.
        alpha (float): Exponent for non-linear superposition.
        W (np.ndarray): Mapping matrix (linear to Bark).
        W_inv (np.ndarray): Inverse mapping matrix (Bark to linear).
        spreadingfuncmatrix (np.ndarray): Spreading function matrix (Bark scale, amplitude ratio).
    Returns:
        np.ndarray: Masking threshold on the linear frequency scale (amplitude relative to 1.0).
    """
    # 1. Map magnitude spectrum to Bark scale (amplitude)
    mXbark = mapping2bark_v3(mX, W)

    # 2. Compute masking effect from signal components on Bark scale (amplitude)
    # Masking effect = (Sum over masker bands i [ (MaskerAmplitude_i * SpreadingFunction_i_to_j)^(alpha) ] ) ^ (1/alpha)
    # Simplified: mTbark_signal = (mXbark^alpha @ spreadingfuncmatrix^alpha)^(1/alpha)
    # The spreadingfuncmatrix already includes the alpha exponent on the spreading part.
    # We need masker amplitude to the power of alpha.
    mTbark_signal = np.dot(mXbark**alpha, spreadingfuncmatrix) # spreadingfuncmatrix is already amp^alpha
    mTbark_signal = mTbark_signal**(1.0 / alpha)

    # 3. Get Threshold in Quiet (LTQ) for each FFT bin in dBFS
    LTQ_dBFS_linear = threshold_in_quiet_dBFS(fs, nfft)
    # Convert LTQ from dBFS to amplitude (relative to 1.0)
    LTQ_amp_linear = 10.0**(LTQ_dBFS_linear / 20.0)

    # 4. Map LTQ amplitude to Bark scale
    LTQ_amp_bark = mapping2bark_v3(LTQ_amp_linear, W)

    # 5. Determine final Bark scale threshold (max of signal masking and quiet threshold)
    mTbark_final = np.maximum(mTbark_signal, LTQ_amp_bark)

    # 6. Map final Bark threshold back to linear frequency scale (amplitude)
    mT_linear = mappingfrombark_v3(mTbark_final, W_inv)

    # 7. Ensure final linear threshold is not lower than the linear threshold in quiet
    mT_linear_final = np.maximum(mT_linear, LTQ_amp_linear)

    # Add a small epsilon to prevent zero threshold values
    mT_linear_final = np.maximum(mT_linear_final, 1e-12) # Use a smaller epsilon

    return mT_linear_final
