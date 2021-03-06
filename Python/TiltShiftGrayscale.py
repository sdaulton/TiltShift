import numpy as np
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from skimage import color
from cython.parallel import prange
import time
import math

# A basic, parallelized Python implementation of 
# the Tilt-Shift effect we hope to achieve in OpenCL

# A method that takes in a matrix of 3x3 pixels and blurs 
# the center pixel based on the surrounding pixels, a 
# bluramount of 1 is full blur and will weight the neighboring
# pixels equally with the pixel that is being modified.  
# While a bluramount of 0 will result in no blurring.
def boxblur(blur_amount, p0, p1, p2, p3, p4, p5, p6, p7, p8):
    # Calculate the blur amount for the central and 
    # neighboring pixels
    self_blur_amount = (9 - (blur_amount * 8)) / 9.0
    other_blur_amount = blur_amount / 9.0
    
    # Sum a weighted average of self and others based on the blur amount
    return (self_blur_amount * p4) + (other_blur_amount * (p0 + p1 + p2 + p3 + p5 + p6 + p7 + p8))
    
# Adjusts the saturation of a pixel    
def saturation(p, value):
    return p * (1 - value)
    
# Adjusts the contrast on a pixel    
def contrast(p, value):
    factor = (259 * (value + 255)) / float(255 * (259 - value))
    return truncate(factor * (p - 128) + 128)
    
# Ensures a pixel's value is between 0 and 255
def truncate(value):
    if value < 0:
        return 0
    elif value > 255:
        return 255
    return value

# Applies the tilt-shift effect onto an image (grayscale for now)
# g_corner_x, and g_corner_y are needed in this Python 
# implementation since we don't have thread methods to get our 
# position.  Here they store the top left corner of the group.
# All of the work for a workgroup happens in one thread in 
# this method
def tiltshift(input_image, output_image, buf, 
              w, h, 
              buf_w, buf_h, halo, 
              sat, con, last_pass,
              focus_m, focus_r,
              g_corner_x, g_corner_y):
        
    # coordinates of the upper left corner of the buffer in image space, including halo
    buf_corner_x = g_corner_x - halo
    buf_corner_y = g_corner_y - halo

    # Load all pixels into the buffer from input_image
    # Loop over y values first, so we can load rows sequentially
    for row in range(0, buf_h):
        for col in range(0, buf_w):
            tmp_x = col
            tmp_y = row
            
            # Now ensure the pixel we are about to load is inside the image's boundaries
            if (buf_corner_x + tmp_x < 0) :
                tmp_x += 1
            elif (buf_corner_x + tmp_x >= w):
                tmp_x -= 1
            
            if (buf_corner_y + tmp_y < 0):
                tmp_y += 1
            elif (buf_corner_y + tmp_y >= h):
                tmp_y -= 1
                
            # Check you are within halo of global
            if ((buf_corner_y + tmp_y < h) and (buf_corner_x + tmp_x < w)):
                #input_image[((buf_corner_y + tmp_y) * w) + buf_corner_x + tmp_x];
                buf[row * buf_w + col] = input_image[buf_corner_y + tmp_y, buf_corner_x + tmp_x];
    
    # Loop over y first so we can calculate the bluramount    
    for ly in range(0, 8):
        # Initialize Global y Position
        y = ly + g_corner_y
        # Initialize Buffer y Position
        buf_y = ly + halo;

        # The blur amount depends on the y-value of the pixel
        blur_amount = 1.0
        distance_to_m = abs(y - focus_m)

        if distance_to_m == 0:
            blur_amount = 0.1
        elif (distance_to_m < focus_r):
            blur_amount = math.log10(y / (distance_to_m / 10.0))
            blur_amount = max(blur_amount, 0)
        if blur_amount < 0.1:
            blur_amount = 0.1
        elif blur_amount > 1.0:
            blur_amount = 1.0
            
        for lx in range(0, 8):
            # Initialize Global x Position
            x = lx + g_corner_x
            # Initialize Buffer x Position
            buf_x = lx + halo;
    
            # Stay in bounds check is necessary due to possible 
            # images with size not nicely divisible by workgroup size
            if ((y < h) and (x < w)):
                p0 = buf[((buf_y - 1) * buf_w) + buf_x - 1]
                p1 = buf[((buf_y - 1) * buf_w) + buf_x]
                p2 = buf[((buf_y - 1) * buf_w) + buf_x + 1]
                p3 = buf[(buf_y * buf_w) + buf_x - 1]
                p4 = buf[(buf_y * buf_w) + buf_x]
                p5 = buf[(buf_y * buf_w) + buf_x + 1]
                p6 = buf[((buf_y + 1) * buf_w) + buf_x - 1]
                p7 = buf[((buf_y + 1) * buf_w) + buf_x]
                p8 = buf[((buf_y + 1) * buf_w) + buf_x + 1];
        
                # Perform boxblur
                blurred_pixel = boxblur(blur_amount, p0, p1, p2, p3, p4, p5, p6, p7, p8)
                    
                # If we're in the last pass, perform the saturation and contrast adjustments as well
                if last_pass:
                    blurred_pixel = saturation(blurred_pixel, sat)
                    blurred_pixel = contrast(blurred_pixel, con)
                output_image[y, x] = blurred_pixel

    # Return the output of the last pass
    return output_image

# Rounds up the size to a be multiple of the group_size
def round_up(global_size, group_size):
    r = global_size % group_size
    if r == 0:
        return global_size
    return global_size + group_size - r

# Run a Python implementation of Tilt-Shift (grayscale)
if __name__ == '__main__':
    # Load the image and convert it to grayscale
    input_image = color.rgb2gray(mpimg.imread('MITBoathouse.png',0))
    plt.imshow(input_image)    
    plt.show()
    
    start_time = time.time()
    output_image = np.zeros_like(input_image)

    ################################
    ### USER CHANGEABLE SETTINGS ###
    ################################
    # Number of Passes - 3 passes approximates Gaussian Blur
    num_passes = 3
    # Saturation - Between 0 and 1
    sat = 0.0
    # Contrast - Between -255 and 255
    con = 0.0
    # The y-index of the center of the in-focus region
    middle_in_focus = 500
    # The number of pixels to either side of the middle_in_focus to keep in focus
    in_focus_radius = 200

    local_size = (8, 8)  # 64 pixels per work group
    global_size = tuple([round_up(g, l) for g, l in zip(input_image.shape[::-1], local_size)])
    width = input_image.shape[1]
    height = input_image.shape[0]
    
    # Set up a (N+2 x N+2) local memory buffer.
    # +2 for 1-pixel halo on all sides
    local_memory = np.zeros((local_size[0] + 2) * (local_size[1] + 2))
    
    # Each work group will have its own private buffer.
    buf_width = local_size[0] + 2
    buf_height = local_size[1] + 2
    halo = 1
    
    print "Image Width %s" % width
    print "Image Height %s" % height
    
    # We will perform 3 passes of the bux blur 
    # effect to approximate Gaussian blurring
    for pass_num in range(num_passes):
        print "In iteration %s of %s" % (pass_num + 1, num_passes)
        # We need to loop over the workgroups here, 
        # because unlike OpenCL, they are not 
        # automatically set up by Python
        last_pass = False
        if pass_num == num_passes - 1:
            print "In Last Pass"
            last_pass = True
        
        # Loop over all groups and call tiltshift once per group
        for group_corner_x in prange(0, global_size[0], local_size[0]):
            for group_corner_y in range(0, global_size[1], local_size[1]):
                #print "GROUP CONRER %s %s" % (group_corner_x, group_corner_y)
                # Run tilt shift over the group and store the results in host_image_tilt_shifted
                tiltshift(input_image, output_image, local_memory, 
                          width, height, 
                          buf_width, buf_height, halo, 
                          sat, con, last_pass, 
                          middle_in_focus, in_focus_radius,
                          group_corner_x, group_corner_y)

        # Now put the output of the last pass into the input of the next pass
        input_image = output_image
    end_time = time.time()
    print "Took %s seconds to run %s passes" % (end_time - start_time, num_passes)   
    
    # Display the new image
    plt.imshow(input_image)    
    plt.show()
    mpimg.imsave("MITBoathouseGrayscaleTS.png", input_image)