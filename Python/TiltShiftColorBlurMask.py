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
    #print "--------"
    #print 0 + p0[0] + p1[0] + p2[0] + p3[0] + p5[0] + p6[0] + p7[0] + p8[0]

    red_v = (self_blur_amount * p4[0]) + (other_blur_amount * (0 + p0[0] + p1[0] + p2[0] + p3[0] + p5[0] + p6[0] + p7[0] + p8[0])) 
    green_v = (self_blur_amount * p4[1]) + (other_blur_amount * (0 + p0[1] + p1[1] + p2[1] + p3[1] + p5[1] + p6[1] + p7[1] + p8[1])) 
    blue_v = (self_blur_amount * p4[2]) + (other_blur_amount * (0 + p0[2] + p1[2] + p2[2] + p3[2] + p5[2] + p6[2] + p7[2] + p8[2]))
    #print "Original %s" % p4
    #print "New %s" % [int(red_v), int(blue_v), int(green_v)]
    #print "--------"
    return [int(red_v), int(green_v), int(blue_v)]
    
# Adjusts the saturation of a pixel    
def saturation(p, value):
    red_v = p[0] * (1 - value) 
    blue_v = p[1] * (1 - value) 
    green_v = p[2] * (1 - value) 
    return [red_v, blue_v, green_v]
    
# Adjusts the contrast on a pixel    
def contrast(p, value):
    factor = (259 * (value + 255)) / float(255 * (259 - value))
    red = truncate(factor * (p[0] - 128) + 128)
    green = truncate(factor * (p[1] - 128) + 128)
    blue = truncate(factor * (p[2] - 128) + 128)
    return [red, green, blue]
    
# Ensures a pixel's value for a color is between 0 and 255
def truncate(value):
    if value < 0:
        value = 0
    elif value > 255:
        value = 255

    return value

# Applies the tilt-shift effect onto an image (grayscale for now)
# g_corner_x, and g_corner_y are needed in this Python 
# implementation since we don't have thread methods to get our 
# position.  Here they store the top left corner of the group.
# All of the work for a workgroup happens in one thread in 
# this method
def tiltshift(input_image, output_image, buf, blur_mask,
              w, h, 
              buf_w, buf_h, halo, 
              l_w, l_h,
              sat, con, last_pass,
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
    # Loop over y first so we can calculate the blur amount    
    for ly in range(0, l_h):
        # Initialize Global y Position
        y = ly + g_corner_y
        # Initialize Buffer y Position
        buf_y = ly + halo;
        
        for lx in range(0, l_w):
            # Initialize Global x Position
            x = lx + g_corner_x
            # Initialize Buffer x Position
            buf_x = lx + halo;
            
            
    
            # Stay in bounds check is necessary due to possible 
            # images with size not nicely divisible by workgroup size
            if ((y < h) and (x < w)):
                # Get blur amount using global x,y
                blur_amount = blur_mask[y,x]
                
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
    
    
# generates horizontal blur mask using focus middle, focus radius, and image height,
# and stores the blur mask in the blur_mask parameter (np.array)
def generate_horizontal_blur_mask(blur_mask, middle_in_focus, in_focus_radius, height):
    # Calculate blur amount for each pixel based on middle_in_focus and in_focus_radius
    
    # Loop over y first so we can calculate the blur amount
    # fade out 20% to blurry so that there is not an abrupt transition
    no_blur_region = .8 * in_focus_radius
    
    # Set blur amount for focus middle
    #blur_row = np.array([blur_mask])
    blur_row = np.zeros_like(blur_mask[0], dtype=np.float)
    blur_mask[middle_in_focus] = blur_row
    # Simulataneously set blur amount for both rows of same distance from middle
    for y in xrange(middle_in_focus - in_focus_radius, middle_in_focus):
        # The blur amount depends on the y-value of the pixel
        distance_to_m = abs(y - middle_in_focus)
        # Note: Because we are iterating over all y's in the focus region, all the y's are within
        # the focus radius.
        # Thus, we need only check if we should fade to blurry so that there is not an abrupt transition
        if distance_to_m > no_blur_region:
            # Calculate blur ammount
            blur_amount = (1.0 / (in_focus_radius - no_blur_region)) * (distance_to_m - no_blur_region) 
        else:
            # No blur
            blur_amount = 0.0
        blur_row.fill(blur_amount)
        if y > 0:
            blur_mask[y] = blur_row
        if middle_in_focus + distance_to_m < height:
            blur_mask[middle_in_focus + distance_to_m] = blur_row
            
# generates horizontal blur mask using focus middle, focus radius, and image height,
# and stores the blur mask in the blur_mask parameter (np.array)            
def generate_circular_blur_mask(blur_mask, middle_in_focus_x,middle_in_focus_y, in_focus_radius, width, height):
    # Calculate blur amount for each pixel based on middle_in_focus and in_focus_radius
    
    
    # fade out 20% to blurry so that there is not an abrupt transition
    no_blur_region = .8 * in_focus_radius
    
    # Set blur amount (no blur) for center of in-focus region
    blur_mask[middle_in_focus_y, middle_in_focus_x] = 0.0
    
    # Loop over x and y first so we can calculate the blur amount
    for x in xrange(middle_in_focus_x - in_focus_radius, middle_in_focus_x):
        for y in xrange(middle_in_focus_y - in_focus_radius, middle_in_focus_y):
            
            # The blur amount depends on the euclidean distance between the pixel and focus center
            x_distance_to_m = x - middle_in_focus_x
            y_distance_to_m = y - middle_in_focus_y
            distance_to_m = (x_distance_to_m ** 2 + y_distance_to_m ** 2) ** 0.5
            
            # Note: Not all values we iterate over are within the focus region, so we must check
            if distance_to_m < no_blur_region:
                # No blur
                blur_amount = 0.0
            # Check if we should fade to blurry so that there is not an abrupt transition
            elif distance_to_m < in_focus_radius:
                blur_amount = (1.0 / (in_focus_radius - no_blur_region)) * (distance_to_m - no_blur_region)
            else:
                # Completely blurred
                blur_amount = 1.0
            
            # Set the blur_amount for 4 pixels of the same distance from the center of the in-focus region
            if x > 0:
                if y > 0:
                    blur_mask[y, x] = blur_amount
                if middle_in_focus_y + y_distance_to_m < height:
                    blur_mask[middle_in_focus_y + y_distance_to_m, x] = blur_amount
            if middle_in_focus_x + x_distance_to_m < width:
                if y > 0:
                    blur_mask[y, middle_in_focus_x + x_distance_to_m] = blur_amount
                if middle_in_focus_y + y_distance_to_m < height:
                    blur_mask[middle_in_focus_y + y_distance_to_m, middle_in_focus_x + x_distance_to_m] = blur_amount
            
    
# Run a Python implementation of Tilt-Shift (grayscale)
if __name__ == '__main__':
    # Load the image and convert it to grayscale
    input_image = mpimg.imread('../MITBoathouse.png',0)
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
    middle_in_focus_y = 420
    # Circle in-focus region, or horizontal in-focus region
    focused_circle = True
    # The x-index of the center of the in-focus region
    # Note: this only matters for circular in-focus region
    middle_in_focus_x = 650
    # The number of pixels distance from middle_in_focus to keep in focus
    in_focus_radius = 200
    ######################################
    ### USER CHANGEABLE SETTINGS - END ###
    ######################################

    local_size = (256, 256)  # This doesn't really affect speed for the Python implementation
    # We need to add [1:] because the first element in this list is the number of colors in RGB, namely 3
    global_size = tuple([round_up(g, l) for g, l in zip(input_image.shape[::-1][1:], local_size)])
    width = input_image.shape[1]
    height = input_image.shape[0]
    
    # Set up a (N+2 x N+2) local memory buffer.
    # +2 for 1-pixel halo on all sides
    local_memory = [[]] * (local_size[0] + 2) * (local_size[1] + 2) #np.zeros((local_size[0] + 2) * (local_size[1] + 2))
    
    # Each work group will have its own private buffer.
    buf_width = local_size[0] + 2
    buf_height = local_size[1] + 2
    halo = 1
    
    print "Image Width %s" % width
    print "Image Height %s" % height
    
    
    # Initialize blur mask to be all 1's (completely blurry)
    # Note: There is one float blur amount per pixel
    blur_mask = np.ones(input_image.shape[:2], dtype=np.float)
    # Generate the blur mask
    if focused_circle:
        generate_circular_blur_mask(blur_mask, middle_in_focus_x, middle_in_focus_y, in_focus_radius, width, height)
    else:
        generate_horizontal_blur_mask(blur_mask, middle_in_focus_y, in_focus_radius, height)
    
    # We will perform 3 passes of the bux blur 
    # effect to approximate Gaussian blurring
    for pass_num in range(num_passes):
        print "In iteration %s of %s" % (pass_num + 1, num_passes)
        # We need to loop over the workgroups here, 
        # because unlike OpenCL, they are not 
        # automatically set up by Python
        last_pass = False
        if pass_num == num_passes - 1:
            print "---Last Pass---"
            last_pass = True
        
        # Loop over all groups and call tiltshift once per group
        for group_corner_x in range(0, global_size[0], local_size[0]):
            for group_corner_y in range(0, global_size[1], local_size[1]):
                #print "GROUP CONRER %s %s" % (group_corner_x, group_corner_y)
                # Run tilt shift over the group and store the results in host_image_tilt_shifted
                tiltshift(input_image, output_image, local_memory, blur_mask,
                          width, height, 
                          buf_width, buf_height, halo, 
                          local_size[0], local_size[1],
                          sat, con, last_pass, 
                          group_corner_x, group_corner_y)

        # Now put the output of the last pass into the input of the next pass
        input_image = output_image
    end_time = time.time()
    print "Took %s seconds to run %s passes" % (end_time - start_time, num_passes)   
    
    # Display the new image
    plt.imshow(input_image)    
    plt.show()
    mpimg.imsave("MITBoathouseColorTS.png", input_image)